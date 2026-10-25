"""Guest self-service creation, privacy and rollback checks in a disposable test schema."""
from datetime import timedelta
import unittest
from unittest.mock import patch

import service
from test_web import WebTests


class PublicBookingTests(WebTests):
    def booking_data(self):
        return {'room_id':1,'check_in':str(self.today+timedelta(days=5)),
                'check_out':str(self.today+timedelta(days=7)),'guests':2,
                'quoted_base':'180','name':'Guest Contact','phone':'0012345','email':'contact@example.test'}

    def test_public_booking_reuses_guest_table_and_marks_unverified_source(self):
        data=self.booking_data()
        self.assertEqual(self.client.get('/book',query_string=data).status_code,200)
        data.update(guest_id=2,staff_id=1,discount_rate='1')
        response=self.post('/book',data)
        self.assertEqual(response.status_code,302)
        row=self.fixture.execute('''SELECT g.name,g.phone,r.booked_nightly_rate,a.source,a.staff_id
            FROM reservation r JOIN guest g USING(guest_id) JOIN reservation_audit a USING(reservation_id)''')[0]
        self.assertEqual((row[0],row[1],str(row[2]),row[3],row[4]),
                         ('Guest Contact','0012345','180.00','public_booking',None))
        body=self.client.get(response.location)
        self.assertEqual(body.status_code,200)
        self.assertIn(b'Reservation confirmed',body.data)
        self.assertNotIn(b'0012345',body.data)
        self.assertNotIn(b'Alice',body.data)
        self.assertEqual(self.app.test_client().get(response.location).status_code,404)
        self.assertEqual(self.client.get('/booking/confirmation/wrong-token').status_code,404)
        self.assertEqual(self.client.get('/booking/confirmation/无效').status_code,404)
        self.assertEqual(self.client.get('/reservations/1').status_code,302)
        self.assertEqual(self.client.get('/?check_in='+data['check_in']+'&check_out='+data['check_out']+'&guests=1').status_code,200)
        self.assertIsNone(service.operation_actor.get())

    def test_public_conflict_stale_price_bad_contact_and_csrf_do_not_create_contacts(self):
        data=self.booking_data()
        original_count=self.fixture.execute('SELECT COUNT(*) FROM guest')[0][0]
        self.assertEqual(self.client.post('/book',data=data).status_code,400)
        for changed in [{'quoted_base':'170'},{'name':' '},{'phone':' '},{'guests':3},
                        {'check_in':'20261025'},{'check_in':'2026-02-30'}]:
            with self.subTest(changed=changed):
                self.assertEqual(self.post('/book',dict(data,**changed)).status_code,400)
                self.assertEqual(self.fixture.execute('SELECT COUNT(*) FROM guest')[0][0],original_count)
        self.assertEqual(self.post('/book',data).status_code,302)
        self.assertEqual(self.post('/book',data).status_code,400)
        self.assertEqual(self.fixture.execute('SELECT COUNT(*) FROM guest')[0][0],original_count+1)

    def test_public_audit_failure_rolls_back_new_contact_and_reservation(self):
        data=self.booking_data()
        original=self.fixture.execute('SELECT COUNT(*) FROM guest')[0][0]
        with patch.object(service,'_history',side_effect=service.BookingError('Audit unavailable')):
            self.assertEqual(self.post('/book',data).status_code,400)
        self.assertEqual(self.fixture.execute('SELECT COUNT(*) FROM guest')[0][0],original)
        self.assertEqual(self.fixture.execute('SELECT COUNT(*) FROM reservation')[0][0],0)

    def test_existing_guest_id_does_not_grant_customer_access(self):
        data=self.booking_data()
        first=self.post('/book',data)
        data['room_id']=2
        second=self.post('/book',data)
        self.assertEqual(self.client.get(first.location).status_code,404)
        self.assertEqual(self.client.get(second.location).status_code,200)
        # Reusing a phone/name is not evidence of identity, so contacts are not silently merged.
        self.assertEqual(self.fixture.execute("SELECT COUNT(*) FROM guest WHERE name='Guest Contact'")[0][0],2)

    def test_english_calendar_markup_and_strict_server_dates(self):
        response=self.client.get('/')
        self.assertIn(b'calendar.js',response.data)
        self.assertIn(b'placeholder="YYYY-MM-DD"',response.data)
        self.assertNotIn(b'type="date"',response.data)
        self.assertEqual(self.client.get('/',query_string={'check_in':'20261025','check_out':'2026-10-26','guests':1}).status_code,400)
        self.login()
        for path in ['/reservations/new','/reservations/multiple']:
            body=self.client.get(path).data
            self.assertNotIn(b'type="date"',body)


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(PublicBookingTests(name) for name in [
        'test_public_booking_reuses_guest_table_and_marks_unverified_source',
        'test_public_conflict_stale_price_bad_contact_and_csrf_do_not_create_contacts',
        'test_public_audit_failure_rolls_back_new_contact_and_reservation',
        'test_existing_guest_id_does_not_grant_customer_access',
        'test_english_calendar_markup_and_strict_server_dates'])


if __name__=='__main__':
    unittest.main(verbosity=2)
