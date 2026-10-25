from getpass import getpass
from datetime import date, datetime
from decimal import Decimal

import psycopg2

import db
import service
import auth


def positive_number(prompt):
    while True:
        raw = input(prompt).strip()
        try:
            value = int(raw)
        except ValueError:
            print('Enter a positive whole number.')
            continue
        if value > 0:
            return value
        print('Enter a positive whole number.')


def required_text(prompt):
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print('This field cannot be blank.')


def read_date(prompt):
    while True:
        raw = input(prompt).strip()
        try:
            value = date.fromisoformat(raw)
        except ValueError:
            print('Enter a valid date in YYYY-MM-DD format, for example 2026-10-25.')
            continue
        if raw != value.isoformat():
            print('Use YYYY-MM-DD format, for example 2026-10-25.')
            continue
        return value


def optional_room_type():
    while True:
        raw = input('Room type ID (blank for all): ').strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError:
            print('Enter a positive room type ID, or leave this blank.')
            continue
        if value > 0:
            return value
        print('Enter a positive room type ID, or leave this blank.')


def confirm(action):
    print(action)
    answer = input('Type YES to continue; anything else cancels: ')
    answer = answer.strip()
    if answer == 'YES':
        return True
    print('Action cancelled; no write was requested.')
    return False


def format_cell(value):
    if value is None:
        return '-'
    if isinstance(value, Decimal):
        return format(value, '.2f')
    if isinstance(value, bool):
        if value == True:
            return 'yes'
        else:
            return 'no'
    if isinstance(value, datetime):
        return value.isoformat(sep=' ', timespec='seconds')
    if isinstance(value, date):
        return value.isoformat()

    text = str(value)
    text = text.replace('\r', ' ')
    text = text.replace('\n', ' ')
    text = text.replace('\t', ' ')
    return text


def print_table(headers, rows):
    rows = list(rows)
    if len(rows) == 0:
        print('No matching records.')
        return

    formatted_rows = []
    for row in rows:
        formatted_row = []
        for value in row:
            text = format_cell(value)
            formatted_row.append(text)
        formatted_rows.append(formatted_row)

    # Column widths.
    column_widths = []
    for header in headers:
        column_widths.append(len(header))

    for row in formatted_rows:
        for column_number in range(len(row)):
            text_length = len(row[column_number])
            if text_length > column_widths[column_number]:
                column_widths[column_number] = text_length

    heading_parts = []
    separator_parts = []
    for column_number in range(len(headers)):
        heading = headers[column_number].ljust(column_widths[column_number])
        heading_parts.append(heading)
        separator = '-' * column_widths[column_number]
        separator_parts.append(separator)
    print(' | '.join(heading_parts))
    print('-+-'.join(separator_parts))

    for row in formatted_rows:
        row_parts = []
        for column_number in range(len(row)):
            cell = row[column_number].ljust(column_widths[column_number])
            row_parts.append(cell)
        print(' | '.join(row_parts))


def stay_inputs():
    print('Enter your stay dates. Check-out must be after check-in.')
    arrival = read_date('Check-in date (YYYY-MM-DD): ')
    while True:
        departure = read_date('Check-out date (YYYY-MM-DD): ')
        if departure > arrival:
            break
        print('Check-out must be after check-in. Enter another check-out date.')
    guests = positive_number('Guest count: ')
    room_type_id = optional_room_type()
    print('Check-in:', arrival.isoformat())
    print('Check-out:', departure.isoformat())
    print('Nights:', (departure - arrival).days)
    print('Guests:', guests)
    if room_type_id is None:
        print('Room type: All room types')
    else:
        print('Room type:', room_type_id)
    return arrival, departure, guests, room_type_id


def show_room_quotes(rows):
    if not rows:
        print('No rooms are available for the selected dates and guest count.')
        print('Please try different dates or another room type.')
        return
    print_table(
        ('Room ID', 'Room no.', 'Type', 'Capacity', 'Nightly quote', 'Total quote'),
        rows,
    )
    if rows:
        print('Quotes do not reserve inventory. Amounts have no agreed currency yet.')


def select_quoted_room(rows):
    while True:
        raw = input('Room ID from the displayed quotes (0 to cancel): ').strip()
        if raw == '0':
            print('Action cancelled; no write was requested.')
            return None
        try:
            room_id = int(raw)
        except ValueError:
            print('Enter a displayed Room ID, or 0 to cancel.')
            continue
        for row in rows:
            if row[0] == room_id:
                return row
        print('Select a Room ID from these quotes, or enter 0 to cancel.')


def search_rooms():
    arrival, departure, guests, room_type_id = stay_inputs()
    rows = service.find_rooms(arrival, departure, guests, room_type_id)
    show_room_quotes(rows)


def register_contact():
    print('Register a new contact only. Existing contacts can reuse their Guest ID.')
    name = required_text('Contact name: ')
    email = input('Email (optional): ').strip()
    if email == '':
        email = None
    phone = required_text('Phone: ')
    print('Name:', name)
    if email is None:
        print('Email: -')
    else:
        print('Email:', email)
    print('Phone:', phone)
    if confirm('Register this booking contact?'):
        guest_id = service.add_guest(name, email, phone)
        print('Contact registered. Guest ID:', guest_id)


def create_booking():
    guest_id = positive_number('Booking contact Guest ID: ')
    arrival, departure, guests, room_type_id = stay_inputs()
    rows = service.find_rooms(arrival, departure, guests, room_type_id)
    show_room_quotes(rows)
    if not rows:
        return
    selected = select_quoted_room(rows)
    if selected is None:
        return
    show_room_quotes([selected])
    print('Booking contact Guest ID:', guest_id)
    if confirm('Create this reservation for the dates and guests shown above?'):
        result = service.create_reservation(
            guest_id, selected[0], arrival, departure, guests,
        )
        print('Reservation created and committed.')
        print_table(('Reservation ID', 'Booked nightly rate', 'Total amount'), [result])


def personal_bookings():
    guest_id = positive_number('Booking contact Guest ID: ')
    rows = service.personal_reservations(guest_id)
    if len(rows) == 0:
        print('No reservations for this Guest ID.')
        return
    show_reservations(rows)


def show_reservations(rows):
    planned_rows = []
    actual_rows = []
    for row in rows:
        planned_row = (
            row[0], row[1], row[2], row[3], row[4],
            row[5], row[6], row[7], row[8]
        )
        planned_rows.append(planned_row)
        actual_row = (row[0], row[9], row[10], row[11])
        actual_rows.append(actual_row)

    print('Planned stay and price')
    print_table(
        ('Reservation ID', 'Room no.', 'Type', 'Check-in', 'Check-out',
         'Guests', 'Nightly rate', 'Total', 'Status'),
        planned_rows
    )
    print('\nActual stay and previous segment')
    print_table(
        ('Reservation ID', 'Actual check-in', 'Actual check-out', 'Previous ID'),
        actual_rows
    )


def staff_reservations():
    print('Leave the search blank to view all reservations.')
    print('Otherwise enter an exact Reservation ID, full contact name or phone.')
    keyword = input('Search: ').strip()
    rows = service.search_reservations(keyword)
    if not rows:
        print('No reservations match this search.')
        return

    contact_rows = []
    booking_rows = []
    for row in rows:
        contact_row = (row[0], row[1], row[2], row[3], row[4], row[5])
        contact_rows.append(contact_row)
        booking_row = (
            row[0], row[5], row[6], row[7], row[8], row[9],
            row[10], row[11], row[12], row[13], row[14], row[15]
        )
        booking_rows.append(booking_row)

    print('Booking contact and room')
    print_table(
        ('Reservation ID', 'Guest ID', 'Contact name', 'Phone', 'Room ID', 'Room no.'),
        contact_rows,
    )
    show_reservations(booking_rows)


def cancel_booking():
    guest_id = positive_number('Booking contact Guest ID: ')
    reservation_id = positive_number('Reservation ID to cancel: ')
    if confirm(f'Cancel reservation {reservation_id} for Guest ID {guest_id}?'):
        service.cancel_reservation(guest_id, reservation_id)
        print('Reservation cancelled and committed.')


def add_roster_entry():
    reservation_id = positive_number('Reservation ID: ')
    full_name = required_text('Actual staying guest full name: ')
    if confirm(f'Add {full_name} to reservation {reservation_id}?'):
        registration_id = service.add_staying_guest(reservation_id, full_name)
        print('Staying guest registered. Registration ID:', registration_id)


def remove_roster_entry():
    reservation_id = positive_number('Reservation ID: ')
    registration_id = positive_number('Registration ID to remove: ')
    if confirm(f'Remove registration {registration_id} from reservation {reservation_id}?'):
        service.remove_staying_guest(reservation_id, registration_id)
        print('Staying guest registration removed and committed.')


def show_roster():
    reservation_id = positive_number('Reservation ID: ')
    print_table(
        ('Registration ID', 'Reservation ID', 'Full name'),
        service.list_staying_guests(reservation_id),
    )


def arrive():
    reservation_id = positive_number('Reservation ID to check in: ')
    if confirm(f'Check in reservation {reservation_id} now?'):
        service.check_in(reservation_id)
        print('Check-in committed; the actual check-in time was recorded.')


def depart():
    reservation_id = positive_number('Reservation ID to check out: ')
    print('This records actual departure and makes the vacated room dirty.')
    print('Planned dates and the agreed price stay unchanged; no refund is calculated.')
    if confirm(f'Check out reservation {reservation_id} now?'):
        service.check_out(reservation_id)
        print('Check-out and room cleaning status committed together.')


def change_open_status():
    room_id = positive_number('Room ID (not the room number): ')
    while True:
        choice = input('1 Open for bookings; 2 Close for bookings: ').strip()
        if choice in ('1', '2'):
            break
        print('Choose 1 or 2.')
    if choice == '1':
        is_open = True
        action = 'open'
    else:
        is_open = False
        action = 'closed' 
    print('Changing this setting does not cancel existing reservations.')
    if confirm(f'Set Room ID {room_id} to {action} for new bookings?'):
        service.set_room_open(room_id, is_open)
        print('Room booking setting committed.')


def change_housekeeping():
    room_id = positive_number('Room ID (not the room number): ')
    while True:
        new_status = input('New status (dirty / cleaning / clean): ').strip().lower()
        if new_status in ('dirty', 'cleaning', 'clean'):
            break
        print('Enter dirty, cleaning or clean.')
    print('Demo cleaning sequence: dirty -> cleaning -> clean.')
    if confirm(f'Set Room ID {room_id} cleaning status to {new_status}?'):
        service.set_housekeeping_status(room_id, new_status)
        print('Room cleaning status committed.')


def extension_inputs():
    reservation_id = positive_number('Current checked-in Reservation ID: ')
    new_check_out = read_date('New final check-out date (YYYY-MM-DD): ')
    print('The new segment starts on the previous segment\'s planned check-out date.')
    print('New final check-out:', new_check_out.isoformat())
    return reservation_id, new_check_out


def show_extension_quotes(rows):
    print_table(
        ('Room ID', 'Room no.', 'Type', 'Capacity', 'Nightly quote',
         'New segment total', 'Preference'),
        rows,
    )
    if rows:
        print('Demo quotes use the current room-type base price; currency is not fixed.')


def extension_options():
    reservation_id, new_check_out = extension_inputs()
    show_extension_quotes(service.find_extension_options(reservation_id, new_check_out))


def create_continuation():
    reservation_id, new_check_out = extension_inputs()
    rows = service.find_extension_options(reservation_id, new_check_out)
    show_extension_quotes(rows)
    if not rows:
        return
    selected = select_quoted_room(rows)
    if selected is None:
        return
    show_extension_quotes([selected])
    print('The new reservation will be confirmed; the current stay will remain checked in.')
    if confirm('Accept this room, new segment dates and displayed rate?'):
        # Use the quoted rate.
        accepted_rate = selected[4]
        result = service.create_extension(
            reservation_id, selected[0], new_check_out, accepted_rate,
        )
        print('Continuation reservation created and committed.')
        print_table(('Reservation ID', 'Booked nightly rate', 'Total amount'), [result])


def activate_segment():
    reservation_id = positive_number('Next confirmed continuation Reservation ID: ')
    print('This ends the previous segment and starts this segment in one transaction.')
    print('A room change makes the old room dirty; a same-room continuation does not.')
    if confirm(f'Activate continuation reservation {reservation_id} now?'):
        service.activate_continuation(reservation_id)
        print('Continuation activated and both segments committed together.')


def modify_booking():
    rid = positive_number('Reservation ID: ')
    arrival = read_date('New check-in (YYYY-MM-DD): ')
    departure = read_date('New check-out (YYYY-MM-DD): ')
    options, revision = service.amendment_options(rid,arrival,departure)
    show_room_quotes(options)
    if not options:
        return
    selected = select_quoted_room(options)
    if selected is None:
        return
    discount = input('Discounted nightly rate (manager only; blank for standard quote): ').strip() or None
    reason = required_text('Reason for change: ')
    print('Selected dates:',arrival,'to',departure,'; standard nightly rate:',selected[4])
    if discount is not None:
        print('Manager discounted nightly rate:',discount)
    if confirm('Confirm modification? An unchanged form preserves the existing agreed rate.'):
        service.amend_reservation(rid,selected[0],arrival,departure,revision,selected[4],reason,discount)
        print('Modification committed. Reservation ID retained; previous allocation released as applicable.')


def book_multiple_rooms():
    contact = positive_number('Booking contact Guest ID: ')
    arrival, departure, _, room_type = stay_inputs()
    options = service.find_rooms(arrival,departure,1,room_type)
    show_room_quotes(options)
    selections = []
    while options:
        selected = select_quoted_room(options)
        if selected is None:
            break
        guests = positive_number('Guests in this room: ')
        discount = input('Discounted nightly rate (manager only; blank for standard quote): ').strip() or None
        reason = required_text('Discount reason: ') if discount is not None else ''
        selections.append({'room_id':selected[0],'guests':guests,'quoted_base':selected[4],
                           'discount_rate':discount,'reason':reason})
        options = [row for row in options if row[0] != selected[0]]
        if input('Add another room? Type YES: ').strip() != 'YES':
            break
    if not selections:
        return
    print_table(('Room ID','Guests','Standard / night','Requested / night'),
                [(s['room_id'],s['guests'],s['quoted_base'],s['discount_rate'] or s['quoted_base']) for s in selections])
    print('Shared dates:',arrival,'to',departure,'. Each room is managed separately after creation.')
    if confirm('Create all selected reservations in one transaction?'):
        results = service.create_reservations(contact,arrival,departure,selections)
        print_table(('Reservation ID','Nightly rate','Stay total'),results)


def show_booking_history():
    for event in service.reservation_history(positive_number('Reservation ID: ')):
        print(event['occurred_at'],event['action'],event['username'] or event['source'],event['reason'])
        print('Before:',event['before'])
        print('After:',event['after'])


def show_role_menu():
    print("""
Hotel Reservation System
1 Customer
2 Staff
0 Exit
""")


def show_menu(role):
    if role == 'customer':
        print("""
Customer Menu
1 View room types
2 Search available rooms
3 Register booking contact
4 Create reservation
5 View my reservations
6 Cancel my reservation
B Back to role selection
0 Exit
""")
    elif role == 'staff':
        print("""
Staff Menu
 1 View room types                 10 View staying guests
 2 View rooms                      11 Check in
 3 Search available rooms          12 Check out
 4 Register new booking contact    13 Open or close room (manager only)
 5 Create reservation              14 Update housekeeping status
 6 View / search reservations      15 View extension options
 7 Cancel reservation              16 Create extension / continuation
 8 Add staying guest               17 Activate continuation
 9 Remove staying guest            18 Booking statistics
19 Book multiple rooms together   20 Modify dates / room / manager rate
21 View reservation history
 B Back to role selection
 0 Exit
""")


def run_customer_option(choice):
    if choice == '1':
        print_table(
            ('Type ID', 'Type', 'Capacity', 'Base nightly rate'), service.list_types(),
        )
    elif choice == '2':
        search_rooms()
    elif choice == '3':
        register_contact()
    elif choice == '4':
        create_booking()
    elif choice == '5':
        personal_bookings()
    elif choice == '6':
        cancel_booking()
    else:
        print('Choose one of the listed customer options.')


def run_option(choice, role, staff=None):
    if role == 'customer':
        token = service.operation_actor.set(('developer_customer',None,None))
        try:
            run_customer_option(choice)
        finally:
            service.operation_actor.reset(token)
    elif role == 'staff':
        run_staff_option(choice, staff)
    else:
        print('Choose Customer or Staff first.')


def run_staff_option(choice, staff):
    if not staff:
        raise auth.AuthError('请先登录员工账号。')
    auth.require_staff(staff['staff_id'], staff['session_version'], manager=choice == '13')
    with service.staff_actor(staff['staff_id'],staff['session_version']):
        return staff_action(choice)


def staff_action(choice):
    if choice == '1':
        print_table(
            ('Type ID', 'Type', 'Capacity', 'Base nightly rate'), service.list_types(),
        )
    elif choice == '2':
        print_table(
            ('Room ID', 'Room no.', 'Type', 'Capacity', 'Base rate', 'Open', 'Cleaning'),
            service.list_rooms(),
        )
    elif choice == '3':
        search_rooms()
    elif choice == '4':
        register_contact()
    elif choice == '5':
        create_booking()
    elif choice == '6':
        staff_reservations()
    elif choice == '7':
        cancel_booking()
    elif choice == '8':
        add_roster_entry()
    elif choice == '9':
        remove_roster_entry()
    elif choice == '10':
        show_roster()
    elif choice == '11':
        arrive()
    elif choice == '12':
        depart()
    elif choice == '13':
        change_open_status()
    elif choice == '14':
        change_housekeeping()
    elif choice == '15':
        extension_options()
    elif choice == '16':
        create_continuation()
    elif choice == '17':
        activate_segment()
    elif choice == '18':
        print('Planned booking values, not collected revenue. No currency is fixed.')
        print_table(
            ('Type', 'All bookings', 'Cancelled', 'Noncancelled booked value'),
            service.booking_statistics(),
        )
    elif choice == '19':
        book_multiple_rooms()
    elif choice == '20':
        modify_booking()
    elif choice == '21':
        show_booking_history()
    else:
        print('Choose one of the listed options.')


def show_database_error(error):
    if isinstance(error, psycopg2.OperationalError):
        print('Database connection failed. Check the service and connection settings.')
        print('If this happened during a write, query its outcome before retrying.')
    elif isinstance(error, psycopg2.IntegrityError):
        print('The database rejected a constraint violation. The write was not completed.')
    elif isinstance(error, psycopg2.ProgrammingError):
        print('Database tables or SQL do not match. Check queries.py and the table definitions.')
    elif isinstance(error, psycopg2.DataError):
        print('The database rejected an input value. Check its size, date or number range.')
    else:
        print('Database operation failed. Check the setup and try again.')
    if error.pgcode:
        print('SQLSTATE:', error.pgcode)
    print('Raw database errors and passwords are not displayed.')


def main():
    try:
        if not db.PASSWORD and not db.PASSFILE:
            db.PASSWORD = getpass('PostgreSQL password (hidden): ')
        role = None
        staff = None
        while True:
            if role is None:
                show_role_menu()
                choice = input('Choose a role: ').strip()
                if choice == '0':
                    print('Goodbye.')
                    return 0
                elif choice == '1':
                    role = 'customer'
                    print('Use your booking contact Guest ID to create or view reservations.')
                    print('New contacts can use option 3 to register first.')
                    print('Please contact staff for check-in, check-out or an extension.')
                elif choice == '2':
                    try:
                        staff = auth.authenticate(input('Staff username: '), getpass('Staff password: '))
                        if staff['must_change_password']:
                            print('首次登录须设置12–128个字符的新密码。')
                            new_password = getpass('New password: ')
                            if new_password != getpass('Confirm new password: '):
                                raise auth.AuthError('两次新密码不一致。')
                            current_password = getpass('Current temporary password: ')
                            staff['session_version'] = auth.change_password(staff['staff_id'],
                                staff['session_version'], current_password, new_password)
                            staff['must_change_password'] = False
                    except auth.AuthError as error:
                        print(error)
                        staff = None
                        continue
                    except psycopg2.Error as error:
                        show_database_error(error)
                        print('请确认已执行 database/staff.sql 或 setup_web.py。')
                        staff = None
                        continue
                    role = 'staff'
                    print('Logged in:', staff['display_name'], '/', staff['role'])
                    print('Use Room ID for actions; Room no. is the door number.')
                else:
                    print('Choose 1 for Customer, 2 for Staff, or 0 to exit.')
                continue

            show_menu(role)
            choice = input('Choose an option: ').strip().upper()
            if choice == '0':
                print('Goodbye.')
                return 0
            if choice == 'B':
                if staff:
                    try:
                        auth.logout(staff['staff_id'], staff['session_version'])
                    except psycopg2.Error as error:
                        show_database_error(error)
                    staff = None
                role = None
                continue
            try:
                run_option(choice, role, staff)
            except auth.AuthError as error:
                print('Not completed:', error)
                role, staff = None, None
            except service.BookingError as error:
                print('Not completed:', error)
            except psycopg2.Error as error:
                show_database_error(error)
            except ValueError as error:
                print('Invalid input:', error)
    except (EOFError, KeyboardInterrupt):
        print('\nStopped. Check any transaction outcome before retrying a write.')
        return 1
    finally:
        # Clear the password on exit.
        db.PASSWORD = ''


if __name__ == '__main__':
    raise SystemExit(main())
