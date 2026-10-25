"""Generate one additive, synthetic demo-data script; never connect or overwrite records."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIRST = ['Olivia', 'Noah', 'Amelia', 'Liam', 'Sophia', 'Lucas', 'Mia', 'Ethan']
LAST = ['Patel', 'Nguyen', 'Brown', 'Wilson', 'Taylor', 'Garcia']
CAPACITY = {1: 1, 2: 2, 3: 4, 4: 4, 5: 2, 6: 2, 7: 2, 8: 5}
RATES = {1: 120, 2: 180, 3: 240, 4: 320, 5: 220, 6: 190, 7: 180, 8: 360}


def quoted(value):
    return 'NULL' if value is None else "'" + str(value).replace("'", "''") + "'"


def day(offset):
    return 'CURRENT_DATE' if offset == 0 else f'CURRENT_DATE {"+" if offset > 0 else "-"} {abs(offset)}'


def main():
    lines = ["/* add fictional demonstration data after seed.sql; run once, without deleting existing rows */",
             'BEGIN;', "SET LOCAL TIME ZONE 'Australia/Sydney';", "SET LOCAL lock_timeout = '5s';",
             'LOCK TABLE guest, room_type, room, reservation, reservation_guest IN SHARE ROW EXCLUSIVE MODE;',
             '', '/* add booking contacts */']
    for number in range(5, 51):
        name = FIRST[(number - 5) % len(FIRST)] + ' ' + LAST[((number - 5) // len(FIRST)) % len(LAST)]
        email = None if number % 4 == 0 else f'guest{number:03d}@example.com'
        phone = f'+61 400 100 {(number // 2):03d}'
        lines.append(f'INSERT INTO guest VALUES ({number}, {quoted(name)}, {quoted(email)}, {quoted(phone)});')
    lines += ['', '/* add room types */']
    for number, name in [(4, 'Suite'), (5, 'Deluxe Double'), (6, 'Twin'), (7, 'Accessible'), (8, 'Family Suite')]:
        lines.append(f'INSERT INTO room_type VALUES ({number}, {quoted(name)}, {CAPACITY[number]}, {RATES[number]:.2f});')
    lines += ['', '/* add physical rooms; the new occupied rooms start clean and open */']
    rooms = {}
    for number in range(7, 41):
        room_type = 1 + (number - 7) % 8
        rooms[number] = room_type
        is_open = number not in (16, 24, 32, 40)
        housekeeping = 'clean' if number <= 10 else ['clean', 'dirty', 'cleaning'][(number - 7) % 3]
        lines.append(f'INSERT INTO room VALUES ({number}, {quoted(str(394 + number))}, {room_type}, '
                     f'{str(is_open).upper()}, {quoted(housekeeping)});')

    records = []
    rosters = []

    def add(reservation, contact, room, start, end, guests, status, price, previous=None, names=None):
        if names is None:
            names = [FIRST[(reservation + j) % len(FIRST)] + ' ' + LAST[(reservation + j) % len(LAST)]
                     for j in range(guests)]
        arrival = f"{day(start)} + TIME '14:00'" if status in ('checked_in', 'checked_out') else 'NULL'
        departure = f"{day(end)} + TIME '10:00'" if status == 'checked_out' else 'NULL'
        if previous is not None:
            arrival = f"{day(start)} + TIME '10:00'"
        created = f"LEAST(CURRENT_TIMESTAMP, {day(start - 7)} + TIME '09:00')"
        records.append((reservation, contact, room, day(start), day(end), guests,
                        f'{price:.2f}', created, quoted(status), arrival, departure,
                        'NULL' if previous is None else previous))
        rosters.extend((reservation, name) for name in names)
        return names

    for i in range(164):
        room = 7 + i % 34
        block = i // 34
        room_type = rooms[room]
        guests = 1 + (i // 3) % CAPACITY[room_type]
        start, end, status = [(-60, -58, 'checked_out'), (-40, -38, 'cancelled'),
                              (15, 18, 'confirmed'), (30, 32, 'confirmed'),
                              (45, 47, 'cancelled')][block]
        if block == 2 and room <= 10:
            start, end, status = -1, 2, 'checked_in'
        add(2001 + i, 5 + (i * 7) % 46, room, start, end, guests,
            status, RATES[room_type] - 5 * (i % 3))

    for i in range(11):
        old_room = 7 + i
        new_room = old_room if i % 2 == 0 else 7 + (i + 1) % 11
        guests = min(2, CAPACITY[rooms[old_room]], CAPACITY[rooms[new_room]])
        parent = 3001 + i * 2
        contact = 5 + i
        start = -120 + i * 5
        names = add(parent, contact, old_room, start, start + 2, guests, 'checked_out', RATES[rooms[old_room]])
        add(parent + 1, contact, new_room, start + 2, start + 4, guests, 'checked_out',
            RATES[rooms[new_room]], previous=parent, names=names)

    lines += ['', '/* add historical, future and continued stays */',
              'INSERT INTO reservation (',
              '  reservation_id, guest_id, room_id, check_in_date, check_out_date, guest_count,',
              '  booked_nightly_rate, created_at, status, actual_check_in_at, actual_check_out_at,',
              '  previous_reservation_id', ')', 'VALUES']
    for i, record in enumerate(records):
        parts = [str(v) for v in record]
        lines += ['  (' + ', '.join(parts[:6]) + ',',
                  '   ' + ', '.join(parts[6:9]) + ',',
                  '   ' + ', '.join(parts[9:]) + ')' + (';' if i == len(records) - 1 else ',')]
    lines += ['', '/* each registration has its own ID, including copied continuation names */']
    for i, (reservation, name) in enumerate(rosters):
        lines.append(f'INSERT INTO reservation_guest VALUES ({20001 + i}, {reservation}, {quoted(name)});')
    lines += ['', '/* advance identity sequences without rewinding previously allocated values */']
    for table, key in [('guest', 'guest_id'), ('room_type', 'room_type_id'), ('room', 'room_id'),
                       ('reservation', 'reservation_id'), ('reservation_guest', 'reservation_guest_id')]:
        sequence = table + '_' + key + '_seq'
        lines += ['SELECT setval(', f"  pg_get_serial_sequence('{table}', '{key}'),",
                  f'  GREATEST((SELECT MAX({key}) FROM {table}), (SELECT last_value FROM {sequence}))', ');']
    lines += ['', 'COMMIT;', '', '/* update planner statistics after loading the demonstration records */']
    lines += [f'ANALYZE {table};' for table in ['guest', 'room_type', 'room', 'reservation', 'reservation_guest']]
    assert len(records) == 186 and len({row[0] for row in records}) == 186
    assert all(row[5] <= CAPACITY[rooms[row[2]]] for row in records)
    assert all(row[0] >= 2001 and row[2] >= 7 for row in records)
    assert len({20001 + i for i in range(len(rosters))}) == len(rosters)
    (HERE / 'seed_more.sql').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Additions: 46 contacts, 5 room types, 34 rooms, 186 reservations,', len(rosters), 'registrations.')
    print('Target totals:', (50, 8, 40, 200, 11 + len(rosters)))


if __name__ == '__main__':
    main()
