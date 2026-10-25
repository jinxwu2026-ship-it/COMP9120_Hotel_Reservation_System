"""Amendment, batch booking, discounts and audit checks in a disposable test schema."""
from datetime import timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch

import psycopg2
from werkzeug.security import generate_password_hash

import db
import service
from test_integration import ServiceIntegrationTests as Fixture
from test_web import WebTests, PASSWORD


class BookingChangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Fixture.setUpClass()
        cls.addClassCleanup(Fixture.doClassCleanups)
        cls.hashed = generate_password_hash(PASSWORD,method='scrypt')

    def setUp(self):
        self.helper = Fixture()
        self.helper.setUp()
        self.today = self.helper.today
        self.start = self.today+timedelta(days=10)
        self.end = self.start+timedelta(days=2)
        Fixture.execute('''TRUNCATE staff RESTART IDENTITY CASCADE;
            INSERT INTO staff(username,display_name,password_hash,role,must_change_password)
            VALUES('manager','Manager',%s,'manager',FALSE),('reception','Front desk',%s,'receptionist',FALSE)''',
            (self.hashed,self.hashed))

    def make_booking(self,room=1):
        with service.staff_actor(2,0):
            return self.helper.booking(room=room,start=self.start)

    def quote(self,rid,start=None,end=None):
        return service.amendment_options(rid,start or self.start,end or self.end)

    def amend(self,rid,room=2,start=None,end=None,revision=None,rate='180',discount=None,actor=2):
        start,end = start or self.start,end or self.end
        revision = revision or self.quote(rid,start,end)[1]
        with service.staff_actor(actor,0):
            return service.amend_reservation(rid,room,start,end,revision,rate,'Guest requested change',discount)

    def batch(self,discount=None):
        return [{'room_id':rid,'guests':2,'quoted_base':'180',
                 'discount_rate':discount,'reason':'Manager goodwill' if discount is not None else ''}
                for rid in [1,2]]

    def test_amend_preserves_id_and_roster_releases_previous_allocation(self):
        rid = self.make_booking()
        with service.staff_actor(2,0):
            service.add_staying_guest(rid,'A < B')
        roster = service.list_staying_guests(rid)
        self.amend(rid,room=3,start=self.start+timedelta(days=2),end=self.end+timedelta(days=3),rate='240')
        self.assertEqual(service.list_staying_guests(rid),roster)
        self.assertEqual(Fixture.execute('SELECT reservation_id,room_id,booked_nightly_rate FROM reservation'),
                         [(rid,3,Decimal('240'))])
        self.assertIn(1,[r[0] for r in service.find_rooms(self.start,self.end,2)])
        self.assertEqual(Fixture.execute('SELECT housekeeping_status FROM room WHERE room_id=1')[0][0],'clean')
        event = service.reservation_history(rid)[0]
        self.assertEqual((event['action'],event['username'],event['before']['room_id'],event['after']['room_id']),
                         ('amend','reception',1,3))

    def test_same_room_overlap_excludes_self_and_unchanged_keeps_discount(self):
        with service.staff_actor(1,0):
            rid = service.create_reservation(1,1,self.start,self.end,2,'150','Goodwill','180')[0]
        self.assertIn(1,[r[0] for r in self.quote(rid)[0]])
        before = len(service.reservation_history(rid))
        self.amend(rid,room=1)
        self.assertEqual(Fixture.execute('SELECT booked_nightly_rate FROM reservation')[0][0],Decimal('150'))
        self.assertEqual(len(service.reservation_history(rid)),before)
        self.amend(rid,room=1,end=self.end+timedelta(days=1))
        self.assertEqual(Fixture.execute('SELECT booked_nightly_rate FROM reservation')[0][0],Decimal('180'))

    def test_amend_conflict_capacity_closed_price_and_stale_leave_original(self):
        rid = self.make_booking()
        original = Fixture.execute('SELECT * FROM reservation WHERE reservation_id=%s',(rid,))
        self.helper.booking(room=2,start=self.start)
        for args in [{'room':2},{'room':4,'rate':'120'},{'room':6,'rate':'240'},
                     {'room':3,'rate':'200'},{'room':3,'rate':'240','revision':'stale'}]:
            with self.subTest(args=args),self.assertRaises(service.BookingError):
                self.amend(rid,**args)
            self.assertEqual(Fixture.execute('SELECT * FROM reservation WHERE reservation_id=%s',(rid,)),original)

    def test_changed_roster_invalidates_open_form(self):
        rid = self.make_booking()
        revision = self.quote(rid)[1]
        with service.staff_actor(2,0):
            service.add_staying_guest(rid,'Alex')
        with self.assertRaises(service.StaleReservation):
            self.amend(rid,revision=revision)

    def test_amendment_policy_and_continuation_history(self):
        current = self.helper.booking(start=self.today)
        with self.assertRaises(service.BookingError):
            self.quote(current)
        rid = self.make_booking()
        Fixture.execute('''INSERT INTO reservation(guest_id,room_id,check_in_date,check_out_date,
            guest_count,booked_nightly_rate,status,previous_reservation_id)
            VALUES(1,2,%s,%s,2,180,'cancelled',%s)''',(self.end,self.end+timedelta(days=1),rid))
        with self.assertRaises(service.BookingError):
            self.quote(rid)
        Fixture.execute("UPDATE reservation SET status='cancelled' WHERE reservation_id=%s",(rid,))
        with self.assertRaises(service.BookingError):
            self.quote(rid)

    def test_manager_discount_rules_and_staff_session_revalidation(self):
        rid = self.make_booking()
        for discount in ['160','-1','181','NaN','Infinity','1.001']:
            with self.subTest(discount=discount),self.assertRaises(service.BookingError):
                self.amend(rid,room=1,discount=discount,actor=2 if discount=='160' else 1)
        with service.staff_actor(1,0),self.assertRaises(service.BookingError):
            service.create_reservation(1,2,self.start,self.end,2,'150',' ','180')
        self.amend(rid,room=1,discount='150',actor=1)
        event = service.reservation_history(rid)[0]
        self.assertEqual((event['action'],event['username']),('discount','manager'))
        self.assertEqual(event['after']['operation_details']['reference_rate'],'180.00')
        Fixture.execute('UPDATE staff SET session_version=session_version+1 WHERE staff_id=1')
        with self.assertRaises(service.BookingError):
            self.amend(rid,room=1,discount='140',actor=1)

    def test_batch_success_per_room_prices_and_separate_reservations(self):
        with service.staff_actor(1,0):
            result = service.create_reservations(1,self.start,self.end,self.batch('150'))
        self.assertEqual(len(result),2)
        self.assertTrue(all(r[1:]==(Decimal('150'),Decimal('300')) for r in result))
        self.assertEqual(Fixture.execute('SELECT COUNT(*) FROM reservation_audit')[0][0],2)
        self.assertTrue(all(service.reservation_history(r[0])[0]['username']=='manager' for r in result))
        Fixture.execute('UPDATE room_type SET base_nightly_rate=200 WHERE room_type_id=1')
        self.assertEqual(sum(r[7] for r in service.personal_reservations(1)),Decimal('600'))

    def test_batch_invalid_room_duplicate_capacity_price_and_discount_are_atomic(self):
        for failure in ['duplicate','capacity','closed','stale_price','reception_discount','bad_date']:
            selections = self.batch()
            if failure=='duplicate':selections[1]['room_id']=1
            if failure=='capacity':selections[1]['guests']=3
            if failure=='closed':selections[1].update(room_id=6,quoted_base='240')
            if failure=='stale_price':selections[1]['quoted_base']='170'
            if failure=='reception_discount':selections[1].update(discount_rate='150',reason='Not authorized')
            with self.subTest(failure=failure),service.staff_actor(2,0),self.assertRaises(service.BookingError):
                service.create_reservations(1,self.start,self.start if failure=='bad_date' else self.end,selections)
            self.assertEqual(Fixture.execute('SELECT COUNT(*) FROM reservation')[0][0],0)
            self.assertEqual(Fixture.execute('SELECT COUNT(*) FROM reservation_audit')[0][0],0)

    def test_batch_conflict_preserves_only_existing_booking(self):
        existing = self.helper.booking(room=2,start=self.start)
        with service.staff_actor(2,0),self.assertRaises(service.BookingError):
            service.create_reservations(1,self.start,self.end,self.batch())
        self.assertEqual(Fixture.execute('SELECT reservation_id FROM reservation'),[(existing,)])

    def test_audit_failure_rolls_back_amendment_and_entire_batch(self):
        rid = self.make_booking()
        before = Fixture.execute('SELECT * FROM reservation')
        with patch.object(service,'_history',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.amend(rid)
        self.assertEqual(Fixture.execute('SELECT * FROM reservation'),before)
        Fixture.execute('TRUNCATE reservation RESTART IDENTITY CASCADE')
        original_history = service._history
        written = []
        def fail_second(*args,**kwargs):
            written.append(args[1])
            if len(written)==2:raise RuntimeError('second audit failed')
            return original_history(*args,**kwargs)
        with service.staff_actor(2,0),patch.object(service,'_history',side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                service.create_reservations(1,self.start,self.end,self.batch())
        self.assertEqual(len(written),2)
        self.assertEqual(Fixture.execute('SELECT COUNT(*) FROM reservation')[0][0],0)
        self.assertEqual(Fixture.execute('SELECT COUNT(*) FROM reservation_audit')[0][0],0)

    def test_concurrent_amendments_do_not_overwrite_each_other(self):
        rid = self.make_booking()
        revision = self.quote(rid)[1]
        self.helper.race([lambda:self.amend(rid,revision=revision),
                          lambda:self.amend(rid,room=3,rate='240',revision=revision)])
        self.assertEqual([e['action'] for e in service.reservation_history(rid)],['amend','create'])

    def test_concurrent_batch_and_single_booking_do_not_double_sell(self):
        def batch():
            with service.staff_actor(2,0):
                return service.create_reservations(1,self.today,self.today+timedelta(days=2),self.batch())
        self.helper.race([batch,lambda:self.helper.booking()])
        self.assertEqual(Fixture.execute('SELECT COUNT(*) FROM reservation WHERE room_id=1')[0][0],1)

    def test_concurrent_amendment_and_booking_recheck_target(self):
        rid = self.make_booking(room=2)
        revision = self.quote(rid)[1]
        self.helper.race([lambda:self.amend(rid,room=1,revision=revision),
                          lambda:self.helper.booking(room=1,start=self.start)])
        self.assertEqual(Fixture.execute('SELECT COUNT(*) FROM reservation WHERE room_id=1')[0][0],1)

    def test_roster_cancel_and_continuation_actions_are_attributed(self):
        rid = self.make_booking()
        with service.staff_actor(2,0):
            registration = service.add_staying_guest(rid,'Alex')
            service.remove_staying_guest(rid,registration)
            service.cancel_reservation(1,rid)
            parent = self.helper.parent()
            child = service.create_extension(parent,2,self.today+timedelta(days=2),'180')[0]
            service.activate_continuation(child)
            service.check_out(child)
        self.assertEqual([e['action'] for e in service.reservation_history(rid)],
                         ['cancel','remove_guest','add_guest','create'])
        self.assertEqual([e['action'] for e in service.reservation_history(child)],
                         ['check_out','activate_continuation','create_continuation'])
        self.assertTrue(all(e['username']=='reception' for e in service.reservation_history(child)))
        self.assertEqual(service.reservation_history(parent)[0]['action'],'activate_continuation')

    def test_missing_actor_and_disabled_actor_cannot_use_new_writes(self):
        with self.assertRaises(service.BookingError):
            service.create_reservations(1,self.start,self.end,self.batch())
        Fixture.execute('UPDATE staff SET is_active=FALSE WHERE staff_id=2')
        with service.staff_actor(2,0),self.assertRaises(service.BookingError):
            service.create_reservations(1,self.start,self.end,self.batch())

    def test_continuation_discount_is_manager_only_and_copied_rate_is_fixed(self):
        parent = self.helper.parent()
        with service.staff_actor(2,0),self.assertRaises(service.BookingError):
            service.create_extension(parent,2,self.today+timedelta(days=2),'180','150','Goodwill')
        with service.staff_actor(1,0):
            child = service.create_extension(parent,2,self.today+timedelta(days=2),'180','150','Goodwill')[0]
            service.activate_continuation(child)
        self.assertEqual(service.reservation_history(child)[-1]['username'],'manager')
        self.assertEqual(Fixture.execute('SELECT booked_nightly_rate FROM reservation WHERE reservation_id=%s',
            (child,))[0][0],Decimal('150'))


class BookingChangeWebTests(WebTests):
    # Run this class through the explicit new test names below; inherited checks remain in test_web.py.
    def test_modify_page_history_and_forged_actor(self):
        self.login('reception')
        start,end = self.today+timedelta(days=5),self.today+timedelta(days=7)
        rid = service.create_reservation(1,1,start,end,2)[0]
        response = self.client.get(f'/reservations/{rid}/modify')
        self.assertEqual(response.status_code,200)
        import re
        revision = re.search(rb'name="revision" value="([a-f0-9]+)"',response.data).group(1).decode()
        data = {'room_id':2,'check_in':str(start),'check_out':str(end),'quoted_base':'180',
                'revision':revision,'reason':'<script>change</script>','staff_id':1}
        self.assertEqual(self.post(f'/reservations/{rid}/modify',data).status_code,302)
        page = self.client.get(f'/reservations/{rid}')
        self.assertIn(b'History',page.data)
        self.assertIn(b'&lt;script&gt;change&lt;/script&gt;',page.data)
        self.assertEqual(service.reservation_history(rid)[0]['username'],'reception')
        self.assertEqual(self.post(f'/reservations/{rid}/modify',data).status_code,409)
        data['revision'] = service.amendment_options(rid,start,end)[1]
        data['discount_rate']='150'
        self.assertEqual(self.post(f'/reservations/{rid}/modify',data).status_code,400)
        self.assertIsNone(service.operation_actor.get())

    def test_http_multiple_review_confirm_and_tampered_discount(self):
        self.login()
        start,end = self.today+timedelta(days=5),self.today+timedelta(days=7)
        self.assertEqual(self.client.get('/reservations/multiple',query_string={
            'check_in':str(start),'check_out':str(end)}).status_code,200)
        data = {'guest_id':1,'room_id':['1','2'],'check_in':str(start),'check_out':str(end),
                'guests_1':1,'guests_2':2,'quoted_base_1':'180','quoted_base_2':'180',
                'discount_rate_1':'150','reason':'Goodwill','stage':'review'}
        page = self.post('/reservations/multiple',data)
        self.assertEqual(page.status_code,200)
        self.assertIn(b'660.00',page.data)
        self.assertEqual(Fixture.execute('SELECT COUNT(*) FROM reservation')[0][0],0)
        data['stage']='confirm'
        self.assertEqual(self.post('/reservations/multiple',data).status_code,200)
        self.assertEqual(Fixture.execute('SELECT COUNT(*) FROM reservation')[0][0],2)
        self.assertTrue(all(Fixture.execute('SELECT staff_id FROM reservation_audit')[i][0]==1 for i in range(2)))
        self.assertEqual(self.client.post('/reservations/multiple',data=data).status_code,400)
        self.post('/logout')
        self.login('reception')
        data['check_in'],data['check_out']=str(end),str(end+timedelta(days=2))
        self.assertEqual(self.post('/reservations/multiple',data).status_code,400)
        self.assertEqual(Fixture.execute('SELECT COUNT(*) FROM reservation')[0][0],2)


def suite():
    result = unittest.defaultTestLoader.loadTestsFromTestCase(BookingChangeTests)
    for name in ['test_modify_page_history_and_forged_actor','test_http_multiple_review_confirm_and_tampered_discount']:
        result.addTest(BookingChangeWebTests(name))
    return result


def load_tests(loader,tests,pattern):
    return suite()


if __name__=='__main__':
    unittest.main(verbosity=2)
