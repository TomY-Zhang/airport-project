import os
from flask import Flask, render_template, redirect, request, session, url_for
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from hashlib import md5
import matplotlib
matplotlib.use('agg')
import matplotlib.pyplot as plt
import numpy as np
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
import time

engine = create_engine(os.getenv("DATABASE"))
db = scoped_session(sessionmaker(bind=engine))

if not os.getenv("DATABASE"):
    raise RuntimeError("DATABASE is not set")

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

MONTHS = {
    1  : 'Jan', 
    2  : 'Feb', 
    3  : 'Mar', 
    4  : 'Apr', 
    5  : 'May', 
    6  : 'Jun', 
    7  : 'Jul', 
    8  : 'Aug', 
    9  : 'Sep', 
    10 : 'Oct', 
    11 : 'Nov', 
    12 : 'Dec'
}

def create_figure(stats, name, y_name):
    objects = stats.keys()
    y_pos = np.arange(len(objects))
    plt.bar(y_pos, stats.values(), align='center', alpha=0.5)
    plt.xticks(y_pos, objects)
    plt.xlabel('Month')
    plt.ylabel(y_name)

    session['time'] = time.time()
    plot_name = name + "_" + str(session['time']) + ".png"

    for filename in os.listdir('static/'):
        if filename.startswith(name + '_'):  # not to remove other images
            os.remove('static/' + filename)

    plt.savefig('static/' + plot_name)
    plt.close()

@app.errorhandler(404)
def page_not_found(e):
    name = session['name'] if 'name' in session else None
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    name = session['name'] if 'name' in session else None
    return render_template('404.html', name=name), 500

@app.route('/', methods=['GET', 'POST'])
def home():
    name = session['name'] if 'name' in session else None

    # Check if not logged in
    if not name:
        return redirect(url_for('login'))
    if session['role'] == 'staff':
        return redirect(url_for('staff_home'))

    spend_filter_error = session['spend-filter-error'] if 'spend-filter-error' in session else None
    comment_error = session['comment_error'] if 'comment_error' in session else None
    comment_success = session['comment_success'] if 'comment_success' in session else None

    if spend_filter_error:
        session.pop('spend-filter-error')
    if comment_error:
        session.pop('comment_error')
    if comment_success:
        session.pop('comment_success')

    # Get flight info from purchased tickets
    query = f"""SELECT DISTINCT ticket_id, P.airline, P.flight_id, P.depart_dt,
                    F.arrival_dt, F.src_airport_code, F.dest_airport_code, F.status
                FROM purchases as P NATURAL JOIN flight as F
                WHERE c_email='{session['username']}' AND P.depart_dt """

    flights = db.execute(query + '>= NOW()').fetchall()
    past_flights = db.execute(query + '< NOW()').fetchall()

    if 'spend-filter' in session:
        session.pop('spend-filter')
    else:
        query = f"""SELECT DATE_TRUNC('month', P.purchase_dt) as month, 
                        DATE_TRUNC('year', P.purchase_dt) as year,
                        sum(T.sold_price) as money_spent
                    FROM purchases as P NATURAL JOIN ticket as T
                    WHERE P.c_email='{session['username']}' AND P.purchase_dt > NOW() - INTERVAL '6 months'
                        AND T.id = P.ticket_id
                    GROUP BY month, year"""
        spending = db.execute(query).fetchall()

        end = date.today()
        start = end - relativedelta(months=5)

        date_range = {}
        while start <= end:
            current = f'{MONTHS[start.month]} {start.year % 100}'
            date_range[current] = 0
            start += relativedelta(months=1)

        for s in spending:
            current = f'{MONTHS[s[0].month]} {s[1].year % 100}'
            date_range[current] = s[2]

        create_figure(date_range, 'spending', '$ spent')

    t = session['time']
    session.pop('time')
    return render_template('index.html', name=name, role=session['role'], flights=flights, past_flights=past_flights, \
        time=str(t), spend_filter_error=spend_filter_error, \
        comment_error=comment_error, comment_success=comment_success)

@app.route('/login')
def login():
    if 'name' in session:
        return redirect(url_for('home'))
    return render_template('login.html', name=None)

@app.route('/register')
def register():
    if 'name' in session:
        if session['role'] == 'customer':
            return redirect(url_for('home'))
        else:
            return redirect(url_for('staff_home'))
    return render_template('register.html', name=None);

@app.route('/staffRegister')
def staff_register():
    if 'name' in session:
        if session['role'] == 'customer':
            return redirect(url_for('home'))
        else:
            return redirect(url_for('staff_home'))
    return render_template('staff_register.html')

@app.route('/loginAuth', methods=['GET', 'POST'])
def loginAuth():
    # Get credentials
    username = request.form['username'].lower()
    password = request.form['password']

    password = md5(password.encode('utf-8')).hexdigest()

    # Check if user is customer
    query = f"SELECT * FROM customer WHERE LOWER(email)='{username}' AND password='{password}'"
    customer = db.execute(query).fetchall()

    # Check if user is staff
    query = f"SELECT * FROM staff WHERE LOWER(username)='{username}' AND password='{password}'"
    staff = db.execute(query).fetchall()

    if customer:
        username, password, name, *_ = customer[0]
        session['username'] = username.lower()
        session['name'] = name.title()
        session['role'] = 'customer'
    elif staff:
        *_, airline, fname, lname, _ = staff[0]
        session['username'] = username.lower()
        session['name'] = f'{fname} {lname}'.title()
        print(session['name'])
        session['role'] = 'staff'
        session['airline'] = airline.lower()
    else:
        # Invalid login
        error = 'Invalid login credentials'
        return render_template('login.html', error=error)
    
    return redirect(url_for('home'))

@app.route('/registerAuth', methods=['GET', 'POST'])
def registerAuth():
    forms = {
        'email'             : None,
        'password'          : None,
        'name'              : None,
        'building_num'      : None,
        'street'            : None,
        'city'              : None,
        'state'             : None,
        'phone_num'         : None,
        'passport_num'      : None,
        'passport_expir'    : None,
        'passport_country'  : None,
        'dob'               : None,
    }

    for key in forms:
        val = request.form[key]
        if (type(val) == str):
            val = val.lower()
        forms[key] = val

    # Check if email already registered in system
    query = f"SELECT * FROM customer WHERE LOWER(email)='{forms['email']}'"
    data = db.execute(query).fetchall()

    if data:
        error = 'Email already registered'
        return render_template('register.html', error=error)
    else:
        try:
            # Wrap insert with try in case input size is invalid (i.e. 60 chars for 50 varchar field)
            password = md5(forms['password'].encode('utf-8')).hexdigest()
            query = f"INSERT INTO customer VALUES('{forms['email']}', '{password}',                     \
                    '{forms['name']}', {forms['building_num']}, '{forms['street']}', '{forms['city']}', \
                    '{forms['state']}', {forms['phone_num']}, {forms['passport_num']},                  \
                    '{forms['passport_expir']}', '{forms['passport_country']}', '{forms['dob']}')"
            db.execute(query)
            db.commit()

            # Create session
            session['username'] = forms['email'].lower()
            session['name'] = forms['name']
            session['role'] = 'customer'

            return redirect(url_for('home'))
        except Exception as e:
            # print(e)
            error = 'Invalid input'
            return render_template('register.html', error=error)

@app.route('/staffRegisterAuth', methods=['GET', 'POST'])
def staffRegisterAuth():
    forms = {
        'username'  : None,
        'password'  : None,
        'airline'   : None,
        'fname'     : None,
        'lname'     : None,
        'dob'       : None,
        'mobile'    : None,
        'work'      : None
    }

    for key in forms:
        val = request.form[key]
        if (type(val) == str):
            val = val.lower()
        forms[key] = val
    
    query = f"SELECT * FROM staff WHERE LOWER(username)='{forms['username']}'"
    data = db.execute(query).fetchall()

    if data:
        error = 'Username already taken'
        return render_template('staff_register.html', error=error)
    else:
        # Staff must enter at least one phone number
        if forms['mobile'] == '' and forms['work'] == '':
            error = 'Please enter at least one phone #'
            return render_template('staff_register.html', error=error)

        # Check if airline exists
        query = f"SELECT * FROM airline WHERE LOWER(name)='{forms['airline']}'"
        data = db.execute(query).fetchall()

        if not data:
            error = 'Airline does not exist'
            return render_template('staff_register.html', error=error)

        try:
            # encode password, then insert data into staff table
            password = md5(forms['password'].encode('utf-8')).hexdigest()
            query = f"INSERT INTO staff VALUES('{forms['username']}', '{password}', \
                    '{forms['airline']}', '{forms['fname']}', '{forms['lname']}', '{forms['dob']}')"
            db.execute(query)
            db.commit()

            # If staff entered mobile phone
            if forms['mobile'] != '':
                query = f"INSERT INTO staff_phone VALUES('{forms['username']}', {forms['mobile']})"
                db.execute(query)
                db.commit()

            # If staff entered work phone
            if forms['work'] != '':
                query = f"INSERT INTO staff_phone VALUES('{forms['username']}', {forms['work']})"
                db.execute(query)
                db.commit()

            # Create session
            session['username'] = forms['username'].lower()
            session['name'] = f"{forms['fname']} {forms['lname']}"
            session['role'] = 'staff'

            return redirect(url_for('home'))

        except Exception as e:
            error = 'Invalid input'
            return render_template('staff_register.html', error=error)

@app.route('/logout')
def logout():
    if 'name' not in session:
        return redirect(url_for('login'))

    # Delete session
    session.pop('name')
    session.pop('username')

    if session['role'] == 'staff':
        session.pop('airline')
    session.pop('role')

    return redirect(url_for('login'))

@app.route('/search')
def search():
    if 'name' in session and session['role'] == 'staff':
        return redirect(url_for('staff_home'))

    name = session['name'] if 'name' in session else None
    role = session['role'] if 'role' in session else None
    purchase_error = session['purchase error'] if 'purchase error' in session else None
    success = session['success'] if 'success' in session else None
    
    if purchase_error:
        session.pop('purchase error')
    if success:
        session.pop('success')

    # Get all future flights
    query = "SELECT * FROM flight WHERE depart_dt >= NOW()"
    flights = db.execute(query)

    return render_template('search.html', role=role, flights=flights, name=name, purchase_error=purchase_error, success=success)

@app.route('/filter', methods=['GET', 'POST'])
def filter():
    depart_date = request.form['depart_date']
    arrival_date = request.form['arrival_date']
    src = request.form['src'].lower()
    dest = request.form['dest'].lower()

    # Build query based on filters entered
    query = "SELECT * FROM flight WHERE depart_dt >= NOW() "
    if depart_date != '':
        query += f"AND CAST(depart_dt as DATE) = '{depart_date}' "
    if arrival_date != '':
        query += f"AND CAST(arrival_dt as DATE) = '{arrival_date}%' "
    if src != '':
        # Get airport codes for source city
        data = db.execute(f"SELECT * FROM airport WHERE LOWER(city)='{src}' ")
        src_codes = [row[0] for row in data]
        src_codes = "('" + "', '".join(src_codes) + "')"
        query += f"AND src_airport_code IN {src_codes} "
    if dest != '':
        # Get airport codes for destination city
        data = db.execute(f"SELECT * FROM airport WHERE LOWER(city)='{dest}' ")
        dest_codes = [row[0] for row in data]
        dest_codes = "('" + "', '".join(dest_codes) + "')"   
        query += f"AND dest_airport_code IN {dest_codes} "

    flights = db.execute(query)
    return render_template('search.html', flights=flights)

@app.route('/purchase', methods=['GET', 'POST'])
def purchase():
    if 'name' not in session:
        return redirect(url_for('login'))
    if session['role'] == 'staff':
        return redirect(url_for('staff_home'))

    # Get all future flights
    query = "SELECT * FROM flight WHERE depart_dt >= NOW()"
    upcoming_flights = db.execute(query)

    row = request.form['row'].split(';')
    [airline, flight_id, depart_dt] = row

    card_type = request.form['card_type']
    card_num = request.form['card_num']
    card_holder = request.form['card_holder']
    card_expir = request.form['card_expir']

    query = f"""SELECT * FROM ticket WHERE LOWER(airline)='{airline}' AND
                flight_id={flight_id} AND
                depart_dt='{depart_dt}'"""
    tickets = db.execute(query).fetchall()

    if not tickets:
        session['purchase error'] = 'Flight is fully booked'
        return redirect(url_for('search'))
    else:
        try:
            query = f"""INSERT INTO purchases VALUES( \
                        '{session['username']}', {tickets[0][0]},
                         {tickets[0][3]}, '{depart_dt}',
                        '{airline}', NOW(), '{card_type}', {card_num},
                        '{card_holder}', '{card_expir}')"""
            db.execute(query)
            db.commit()

            session['success'] = "Successfully purchased!"
            return redirect(url_for('search'))
        except Exception as e:
            session['purchase error'] = 'Invalid credit info'
            return redirect(url_for('search'))

@app.route('/cancel', methods=['POST', 'GET'])
def cancel():
    if 'name' not in session:
        return redirect(url_for('login'))
    if session['role'] == 'staff':
        return redirect(url_for('staff_home'))

    row = request.form['row'].split(',')
    [ticket_id, airline, flight_id, depart_dt] = row

    query = f"""DELETE FROM purchases
                WHERE c_email='{session['username']}' AND ticket_id={ticket_id} AND
                    airline='{airline}' AND flight_id={flight_id} AND depart_dt='{depart_dt}'"""

    db.execute(query)
    db.commit()

    return redirect(url_for('home'))

@app.route('/spend-filter', methods=['POST', 'GET'])
def spend_filter():
    if 'name' not in session:
        return redirect(url_for('login'))
    if session['role'] == 'staff':
        return redirect(url_for('staff_home'))

    start = request.form['start_date']
    end = request.form['end_date']

    if start > end:
        session['spend-filter-error'] = 'Invalid date range'
        return redirect(url_for('home'))

    query = f"""SELECT DATE_TRUNC('month', P.purchase_dt) as month,
                    DATE_TRUNC('year', P.purchase_dt) as year,
                    sum(T.sold_price) as money_spent
                FROM purchases as P NATURAL JOIN ticket as T
                WHERE LOWER(P.c_email)='{session['username']}' 
                    AND CAST(P.purchase_dt as DATE) >= '{start}'
                    AND CAST(P.purchase_dt as DATE) <= '{end}'
                    AND T.id = P.ticket_id
                GROUP BY month, year"""
    spending = db.execute(query).fetchall()
    
    start_date = start.split('-')
    end_date = end.split('-')

    start = datetime(int(start_date[0]), int(start_date[1]), int(start_date[2]))
    end = datetime(int(end_date[0]), int(end_date[1]), int(end_date[2]))

    date_range = {}
    while start <= end:
        current = f'{MONTHS[start.month]} {start.year % 100}'
        date_range[current] = 0
        start += relativedelta(months=1)

    for s in spending:
        current = f'{MONTHS[s[0].month]} {s[1].year % 100}'
        date_range[current] = s[2]

    create_figure(date_range, 'spending', '$ spent')

    session['spend-filter'] = True
    return redirect(url_for('home'))

@app.route("/comment", methods=['POST', 'GET'])
def comment():
    if 'name' not in session:
        return redirect(url_for('login'))
    if session['role'] == 'staff':
        return redirect(url_for('staff_home'))

    ticket_id = request.form['ticket_id']
    airline = request.form['airline']
    flight_id = request.form['flight_id']
    depart_dt = request.form['depart_date'] + ' ' + request.form['depart_time'] + ':00'
    rating = request.form['rating']
    comment = request.form['comment']

    now = datetime.now()
    flight_dt = datetime.strptime(depart_dt, '%Y-%m-%d %H:%M:%S')
    if now <= flight_dt:
        error = 'Can only rate and comment on past flights!'
        session['comment_error'] = error
        return redirect(url_for('home'))

    query = f"""SELECT *
                FROM purchases
                WHERE c_email='{session['username']}'
                    AND ticket_id={ticket_id}
                    AND airline='{airline}'
                    AND flight_id={flight_id}
                    AND depart_dt='{flight_dt}'"""
    
    results = db.execute(query).fetchall()
    if not results:
        error = 'Have not flown on such flight or flight does not exist'
        session['comment_error'] = error
        return redirect(url_for('home'))

    query = f"""INSERT INTO customer_flight VALUES (
                    '{session['username']}',
                     {flight_id},
                    '{depart_dt}',
                    '{airline}',
                     {rating},
                    '{comment}'
                )"""

    db.execute(query)
    db.commit()

    session['comment_success'] = 'Rating & comment successfully submitted'
    return redirect(url_for('home'))

@app.route('/staff_home')
def staff_home():
    if 'name' not in session:
        return redirect(url_for('login'))
    if session['role'] != 'staff':
        return redirect(url_for('home'))

    create_error = session['create_error'] if 'create_error' in session else None
    change_error = session['change_error'] if 'change_error' in session else None
    add_plane_error = session['add_plane_error'] if 'add_plane_error' in session else None

    if create_error:
        session.pop('create_error')
    if change_error:
        session.pop('change_error')
    if add_plane_error:
        session.pop('add_plane_error')

    if 'flights' in session:
        flights = session['flights']
        session.pop('flights')
    else:
        query = f"""SELECT * FROM flight WHERE LOWER(airline)='{session['airline']}'
                    AND depart_dt > NOW() AND depart_dt <= NOW() + INTERVAL '30 days'
                    ORDER BY id ASC"""
        flights = db.execute(query).fetchall()

    query = f"""SELECT email, name, ticket_id, flight_id, depart_dt
                FROM purchases as P, customer as C
                WHERE P.c_email=C.email AND LOWER(airline)='{session['airline']}'
                ORDER BY email ASC"""
    customers = db.execute(query).fetchall()

    query = f"""SELECT * FROM airplane WHERE LOWER(airline)='{session['airline']}'"""
    planes = db.execute(query)

    return render_template('staff_home.html', name=session['name'], role=session['role'], default=True, \
        airline=session['airline'].title(), flights=flights, customers=customers, planes=planes, \
        create_error=create_error, change_error=change_error, add_plane_error=add_plane_error)

@app.route('/staff-filter', methods=['GET', 'POST'])
def staff_filter():
    if 'name' not in session:
        return redirect(url_for('login'))
    if session['role'] != 'staff':
        return redirect(url_for('home'))

    start_date = request.form['start_date']
    end_date = request.form['end_date']
    src = request.form['src'].lower()
    dest = request.form['dest'].lower()

    query = f"""SELECT *
                FROM flight
                WHERE LOWER(airline)='{session['airline']}' """

    if start_date != '':
        query += f"AND CAST(depart_dt as DATE) >= '{start_date}' "

    if end_date != '':
        query += f"AND CAST(arrival_dt as DATE) <= '{end_date}' "

    if src != '':
        # Get airport codes for source city
        data = db.execute(f"SELECT * FROM airport WHERE LOWER(city)='{src}' ")
        src_codes = [row[0] for row in data]
        src_codes = "('" + "', '".join(src_codes) + "')"

        query += f"AND src_airport_code IN {src_codes} "
    if dest != '':
        # Get airport codes for destination city
        data = db.execute(f"SELECT * FROM airport WHERE LOWER(city)='{dest}' ")
        dest_codes = [row[0] for row in data]
        dest_codes = "('" + "', '".join(dest_codes) + "')"   

        query += f"AND dest_airport_code IN {dest_codes} "
    
    flights = db.execute(query).fetchall()
    
    flight_ids = '(' + ','.join([str(row[1]) for row in flights]) + ')'
    customers = []
    if flight_ids != '()':
        query = f"""SELECT email, name, ticket_id, flight_id, depart_dt
                    FROM purchases as P, customer as C
                    WHERE LOWER(P.c_email)=LOWER(C.email) AND flight_id IN {flight_ids}
                    ORDER BY email ASC"""
        customers = db.execute(query).fetchall()

    return render_template('staff_home.html', name=session['name'], role=session['role'],\
        airline=session['airline'].title(), flights=flights, customers=customers)

@app.route('/staff-create-flight', methods=['GET', 'POST'])
def staff_create_flight():
    if 'name' not in session:
        return redirect(url_for('login'))
    if session['role'] != 'staff':
        return redirect(url_for('home'))

    airline = session['airline']
    flight_id = request.form['flight_id']
    depart_dt = request.form['depart_date'] + ' ' + request.form['depart_time'] + ':00'

    query = f"""SELECT *
                FROM flight
                WHERE airline='{airline}' AND id={flight_id} AND depart_dt='{depart_dt}'"""
    flights = db.execute(query).fetchall()

    if flights:
        session['create_error'] = f'Flight with ID {flight_id} already exists'
        return redirect(url_for('staff_home'))

    plane_id = request.form['plane_id']
    query = f"""SELECT * FROM airplane WHERE id={plane_id} AND airline='{airline}'"""
    planes = db.execute(query).fetchall()

    if not planes:
        session['create_error'] = 'Plane does not exist or does not belong to ' + airline
        return redirect(url_for('staff_home'))

    arrival_dt = request.form['arrival_date'] + ' ' + request.form['arrival_time'] + ':00'
    if depart_dt >= arrival_dt:
        session['create_error'] = 'Invalid departure and arrival datetimes'
        return redirect(url_for('staff_home'))

    src = request.form['src'].upper()
    dest = request.form['dest'].upper()
    status = request.form['status']
    base_price = request.form['base_price']

    query = f"""INSERT INTO flight VALUES(
                    '{airline}', {flight_id}, '{depart_dt}', '{arrival_dt}', '{src}', '{dest}',\
                    {plane_id}, '{status}', {base_price}
                )"""
    db.execute(query)
    db.commit()

    return redirect(url_for('staff_home'))

@app.route('/staff-change-status', methods=['GET', 'POST'])
def staff_change_status():
    if 'name' not in session:
        return redirect(url_for('login'))
    if session['role'] != 'staff':
        return redirect(url_for('home'))

    row = request.form['row'].split(';')
    status = request.form['status']

    [airline, flight_id, depart_dt] = row

    query = f"""UPDATE flight
                SET status='{status}'
                WHERE LOWER(airline)='{airline}'
                    AND depart_dt='{depart_dt}'
                    AND id={flight_id}"""

    # db.execute(query, (status, airline, depart_dt, int(flight_id)))
    db.execute(query)
    db.commit()

    return redirect(url_for('staff_home'))

@app.route('/staff-add-plane', methods=['GET', 'POST'])
def staff_add_plane():
    if 'name' not in session:
        return redirect(url_for('login'))
    if session['role'] != 'staff':
        return redirect(url_for('home'))

    # Check if plane_id already exists
    plane_id = request.form['plane_id']
    query = f"SELECT * FROM airplane WHERE id={plane_id} AND LOWER(airline)='{session['airline']}'"
    planes = db.execute(query).fetchall()
    if planes:
        session['add_plane_error'] = f'Plane with ID {plane_id} already exists'
        return redirect(url_for('home'))

    airline = session['airline']
    num_seats = request.form['num_seats']
    manufacturer = request.form['manufacturer'].lower()
    age = request.form['age']

    query = f"""INSERT INTO airplane VALUES (
                    '{airline}', {plane_id}, {num_seats}, '{manufacturer}', {age}
                )"""
    db.execute(query)
    db.commit()

    return redirect(url_for('staff_home'))

@app.route('/staff-add-airport', methods=['GET', 'POST'])
def staff_add_airport():
    if 'name' not in session:
        return redirect(url_for('login'))
    if session['role'] != 'staff':
        return redirect(url_for('home'))

    code = request.form['code']
    name = request.form['name'].lower()
    city = request.form['city'].lower()
    country = request.form['country'].lower()
    airport_type = request.form['type']

    query = f"""INSERT INTO airport VALUES (
                    '{code}', '{name}', '{city}', '{country}', '{airport_type}'
                )"""
    db.execute(query)
    db.commit()

    return redirect(url_for('staff_home'))

@app.route('/staff_view')
def staff_view():
    if 'name' not in session:
        return redirect(url_for('login'))
    if session['role'] != 'staff':
        return redirect(url_for('home'))

    ticket_filter_error = session['ticket-filter-error'] if 'ticket-filter-error' in session else None
    t = str(session['time']) if 'time' in session else None
    if ticket_filter_error:
        session.pop('ticket-filter-error')
    if t:
        session.pop('time')
    
    # Get all flights
    query = f"""SELECT F.id, F.depart_dt, F.arrival_dt, F.src_airport_code, F.dest_airport_code, AVG(rating)
                FROM flight as F NATURAL JOIN customer_flight as CF
                WHERE F.id=CF.flight_id AND LOWER(F.airline)='{session['airline']}'
                GROUP BY F.id, F.depart_dt, F.arrival_dt, F.src_airport_code, F.dest_airport_code"""
    flights = db.execute(query)

    query = f"""SELECT * FROM customer_flight WHERE LOWER(airline)='{session['airline']}'"""
    comments = db.execute(query)

    query = f"""SELECT c_email, name
                FROM purchases, customer
                WHERE c_email=email AND LOWER(airline)='{session['airline']}'
                GROUP BY c_email, name
                HAVING COUNT(flight_id) >= ALL(
                    SELECT COUNT(flight_id)
                    FROM purchases
                    WHERE LOWER(airline)='{session['airline']}'
                    GROUP BY c_email
                )"""
    frequent = db.execute(query).fetchall()[0]

    # get revenue from past month
    query = f"""SELECT sum(sold_price)
                FROM purchases NATURAL JOIN ticket
                WHERE ticket_id=id 
                    AND LOWER(airline) = '{session['airline']}'
                    AND purchase_dt >= NOW() - INTERVAL '1 month'"""
    
    sales_month = db.execute(query).fetchall()[0][0]
    if not sales_month:
        sales_month = 0

    # get revenu from past yera
    query = f"""SELECT sum(sold_price)
                FROM purchases NATURAL JOIN ticket
                WHERE ticket_id=id 
                    AND LOWER(airline) = '{session['airline']}'
                    AND purchase_dt >= NOW() - INTERVAL '1 year'"""
    sales_year = db.execute(query).fetchall()[0][0]
    if not sales_year:
        sales_year = 0

    # get revenue by travel class
    sales_class = []
    classes = ['first', 'business', 'economy']
    for c in classes:
        query = f"""SELECT sum(sold_price)
                    FROM purchases NATURAL JOIN ticket
                    WHERE ticket_id=id 
                        AND LOWER(airline) = '{session['airline']}'
                        AND class='{c}'"""
        data = db.execute(query).fetchall()[0][0]
        if not data:
            data = 0
        sales_class.append(data)

    # get top 3 most popular destinations in last year
    query = f"""SELECT F.dest_airport_code, COUNT(P.ticket_id)
                FROM purchases as P NATURAL JOIN flight as F
                WHERE P.flight_id=F.id
                    AND P.depart_dt >= NOW() - INTERVAL '3 months'
                    AND LOWER(airline) = '{session['airline']}'
                GROUP BY F.dest_airport_code
                ORDER BY COUNT(P.ticket_id) DESC
                LIMIT 3 """
    codes = db.execute(query).fetchall()
    month_codes = ''
    if codes:
        month_codes = ', '.join([row[0] for row in codes])

    # get top 3 most popular destinations in last 3 months
    query = f"""SELECT F.dest_airport_code, COUNT(P.ticket_id)
                FROM purchases as P NATURAL JOIN flight as F
                WHERE P.flight_id=F.id
                    AND P.depart_dt >= NOW() - INTERVAL '1 year'
                    AND LOWER(airline) = '{session['airline']}'
                GROUP BY F.dest_airport_code
                ORDER BY COUNT(P.ticket_id) DESC
                LIMIT 3 """
    codes = db.execute(query).fetchall()
    year_codes = ''
    if codes:
        year_codes = ', '.join([row[0] for row in codes])

    return render_template('staff_view.html', name=session['name'], role=session['role'], \
        flights=flights, comments=comments, frequent=frequent, ticket_filter_error=ticket_filter_error, \
        time=t, sales_month=sales_month, sales_year=sales_year, sales_class=sales_class, \
        month_codes=month_codes, year_codes=year_codes)

@app.route('/staff-customer-flight', methods=['POST', 'GET'])
def staff_customer_flights():
    if 'name' not in session:
        return redirect(url_for('login'))
    if session['role'] != 'staff':
        return redirect(url_for('home'))

    ticket_filter_error = session['ticket-filter-error'] if 'ticket-filter-error' in session else None
    t = str(session['time']) if 'time' in session else None
    if ticket_filter_error:
        session.pop('ticket-filter-error')
    if t:
        session.pop('time')
    
    # Get all flights
    query = f"""SELECT F.id, F.depart_dt, F.arrival_dt, F.src_airport_code, F.dest_airport_code, AVG(rating)
                FROM flight as F NATURAL JOIN customer_flight as CF
                WHERE F.id=CF.flight_id AND LOWER(F.airline)='{session['airline']}'
                GROUP BY F.id, F.depart_dt, F.arrival_dt, F.src_airport_code, F.dest_airport_code"""
    flights = db.execute(query)

    query = f"""SELECT * FROM customer_flight WHERE LOWER(airline)='{session['airline']}'"""
    comments = db.execute(query)

    query = f"""SELECT c_email, name
                FROM purchases, customer
                WHERE c_email=email AND LOWER(airline)='{session['airline']}'
                GROUP BY c_email, name
                HAVING COUNT(flight_id) >= ALL(
                    SELECT COUNT(flight_id)
                    FROM purchases
                    WHERE LOWER(airline)='{session['airline']}'
                    GROUP BY c_email
                )"""
    frequent = db.execute(query).fetchall()[0]

    # get revenue from past month
    query = f"""SELECT sum(sold_price)
                FROM purchases NATURAL JOIN ticket
                WHERE ticket_id=id 
                    AND LOWER(airline) = '{session['airline']}'
                    AND purchase_dt >= NOW() - INTERVAL '1 month'"""
    
    sales_month = db.execute(query).fetchall()[0][0]
    if not sales_month:
        sales_month = 0

    # get revenu from past yera
    query = f"""SELECT sum(sold_price)
                FROM purchases NATURAL JOIN ticket
                WHERE ticket_id=id 
                    AND LOWER(airline) = '{session['airline']}'
                    AND purchase_dt >= NOW() - INTERVAL '1 year'"""
    sales_year = db.execute(query).fetchall()[0][0]
    if not sales_year:
        sales_year = 0

    # get revenue by travel class
    sales_class = []
    classes = ['first', 'business', 'economy']
    for c in classes:
        query = f"""SELECT sum(sold_price)
                    FROM purchases NATURAL JOIN ticket
                    WHERE ticket_id=id 
                        AND LOWER(airline) = '{session['airline']}'
                        AND class='{c}'"""
        data = db.execute(query).fetchall()[0][0]
        if not data:
            data = 0
        sales_class.append(data)

    # get top 3 most popular destinations in last 3 months
    query = f"""SELECT """

    # Get list of flights based on customer email
    email = request.form['email'].lower()
    query = f"""SELECT flight_id, depart_dt 
                FROM purchases 
                WHERE LOWER(c_email)='{email}' AND depart_dt < NOW() """
    customer_flights = db.execute(query)

    return render_template('staff_view.html', name=session['name'], role=session['role'], \
        flights=flights, comments=comments, frequent=frequent, customer_flights=customer_flights,
        ticket_filter_error=ticket_filter_error, time=t, sales_month=sales_month, sales_year=sales_year, \
        sales_class=sales_class)

@app.route('/staff-ticket-filter', methods=['GET', 'POST'])
def staff_ticket_filter():
    if 'name' not in session:
        return redirect(url_for('login'))
    if session['role'] != 'staff':
        return redirect(url_for('home'))

    start = request.form['start']
    end = request.form['end']

    start = datetime.strptime(start, '%Y-%m-%d')
    end = datetime.strptime(end, '%Y-%m-%d')

    if start > end:
        session['ticket-filter-error'] = 'Invalid date range'
        return redirect(url_for('staff_view'))

    query = f"""SELECT DATE_TRUNC('month', P.purchase_dt) as month,
                    DATE_TRUNC('year', P.purchase_dt) as year,
                    COUNT(P.purchase_dt)
                FROM purchases as P NATURAL JOIN ticket as T
                WHERE LOWER(airline) = '{session['airline']}'
                    AND CAST(P.purchase_dt as DATE) >= '{start}'
                    AND CAST(P.purchase_dt as DATE) <= '{end}'
                    AND T.id = P.ticket_id
                GROUP BY month, year"""
    tickets = db.execute(query).fetchall()

    date_range = {}
    while start <= end:
        current = f'{MONTHS[start.month]} {start.year % 100}'
        date_range[current] = 0
        start += relativedelta(months=1)

    for t in tickets:
        current = f'{MONTHS[t[0].month]} {t[1].year % 100}'
        date_range[current] = t[2]

    create_figure(date_range, 'sales', 'Tickets sold')
    return redirect(url_for('staff_view'))
