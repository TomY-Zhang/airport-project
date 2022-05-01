import os
import requests
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
session

if not os.getenv("DATABASE"):
    raise RuntimeError("DATABASE is not set")

app = Flask(__name__)
app.config["CACHE_TYPE"] = "null"
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

def create_figure(spending):
    objects = spending.keys()
    y_pos = np.arange(len(objects))
    plt.bar(y_pos, spending.values(), align='center', alpha=0.5)
    plt.xticks(y_pos, objects)
    plt.xlabel('Month')
    plt.ylabel('$ spent')

    session['time'] = time.time()
    plot_name = "spending_" + str(session['time']) + ".png"

    for filename in os.listdir('static/'):
        if filename.startswith('spending_'):  # not to remove other images
            os.remove('static/' + filename)

    plt.savefig('static/' + plot_name)
    plt.close()

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.route('/', methods=['GET', 'POST'])
def home():
    name = session['name'] if 'name' in session else None

    # Check if not logged in
    if not name or session['role'] == 'staff':
        return redirect(url_for('login'))

    cancel_error = session['cancel_error'] if 'cancel_error' in session else None
    spend_filter_error = session['spend-filter-error'] if 'spend-filter-error' in session else None
    comment_error = session['comment_error'] if 'comment_error' in session else None
    comment_success = session['comment_success'] if 'comment_success' in session else None

    if cancel_error:
        session.pop('cancel_error')
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

        create_figure(date_range)

    t = session['time']
    session.pop('time')
    return render_template('index.html', name=name, flights=flights, past_flights=past_flights, \
        cancel_error=cancel_error, time=str(t), spend_filter_error=spend_filter_error, \
        comment_error=comment_error, comment_success=comment_success)

@app.route('/login')
def login():
    if 'name' in session:
        return redirect(url_for('home'))
    return render_template('login.html', name=None)

@app.route('/register')
def register():
    if 'name' in session:
        return redirect(url_for('home'))
    return render_template('register.html', name=None);

@app.route('/staffRegister')
def staff_register():
    if 'name' in session:
        return redirect(url_for('home'))
    return render_template('staff_register.html')

@app.route('/loginAuth', methods=['GET', 'POST'])
def loginAuth():
    # Get credentials
    username = request.form['username']
    password = request.form['password']

    password = md5(password.encode('utf-8')).hexdigest()

    # Check if user is customer
    query = f"SELECT * FROM customer WHERE email='{username}' AND password='{password}'"
    customer = db.execute(query).fetchall()

    # Check if user is staff
    query = f"SELECT * FROM staff WHERE username='{username}' AND password='{password}'"
    staff = db.execute(query).fetchall()

    if customer:
        username, password, name, *_ = customer[0]
        session['username'] = username
        session['name'] = name
        session['role'] = 'customer'
    elif staff:
        *_, fname, lname, dob = staff[0]
        session['username'] = username
        session['name'] = f'{fname} {lname}'
        session['role'] = 'staff'
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
        forms[key] = request.form[key]

    # Check if email already registered in system
    query = f"SELECT * FROM customer WHERE email='{forms['email']}'"
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
            session['username'] = forms['email']
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
        forms[key] = request.form[key]
    
    query = f"SELECT * FROM staff WHERE username='{forms['username']}'"
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
        query = f"SELECT * FROM airline WHERE name='{forms['airline']}'"
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
            session['username'] = forms['username']
            session['name'] = f"{forms['fname']} {forms['lname']}"
            session['role'] = 'staff'

            return redirect(url_for('home'))

        except Exception as e:
            error = 'Invalid input'
            return render_template('staff_register.html', error=error)

@app.route('/logout')
def logout():
    # Delete session
    session.pop('username')
    session.pop('name')
    session.pop('role')
    return redirect(url_for('login'))

@app.route('/search')
def search():
    name = session['name'] if 'name' in session else None
    purchase_error = session['purchase error'] if 'purchase error' in session else None
    success = session['success'] if 'success' in session else None
    
    if purchase_error:
        session.pop('purchase error')
    if success:
        session.pop('success')

    # Get all future flights
    query = "SELECT * FROM flight WHERE depart_dt >= NOW()"
    flights = db.execute(query)

    return render_template('search.html', flights=flights, name=name, purchase_error=purchase_error, success=success)

@app.route('/filter', methods=['GET', 'POST'])
def filter():
    depart_date = request.form['depart_date']
    arrival_date = request.form['arrival_date']
    src = request.form['src']
    dest = request.form['dest']

    # Build query based on filters entered
    query = "SELECT * FROM flight WHERE depart_dt >= NOW() "
    if depart_date != '':
        query += f"AND CAST(depart_dt as DATE) = '{depart_date}' "
    if arrival_date != '':
        query += f"AND CAST(arrival_dt as DATE) = '{arrival_date}%' "
    if src != '':
        # Get airport codes for source city
        data = db.execute(f"SELECT * FROM airport WHERE city='{src}' ")
        src_codes = [row[0] for row in data]
        src_codes = "('" + "', '".join(src_codes) + "')"
        query += f"AND src_airport_code IN {src_codes} "
    if dest != '':
        # Get airport codes for destination city
        data = db.execute(f"SELECT * FROM airport WHERE city='{dest}' ")
        dest_codes = [row[0] for row in data]
        dest_codes = "('" + "', '".join(dest_codes) + "')"   
        query += f"AND dest_airport_code IN {dest_codes} "

    flights = db.execute(query)
    return render_template('search.html', flights=flights)

@app.route('/purchase', methods=['GET', 'POST'])
def purchase():
    if 'name' not in session or session['role'] == 'staff':
        return redirect(url_for('search'))

    # Get all future flights
    query = "SELECT * FROM flight WHERE depart_dt >= NOW()"
    upcoming_flights = db.execute(query)

    names = ['airline', 'flight_id', 'depart_date', 'depart_time', \
             'card_type', 'card_num', 'card_holder', 'card_expir']
    forms = {}
    for name in names:
        forms[name] = request.form[name]

    query = f"""SELECT * FROM ticket WHERE airline='{forms['airline']}' AND
                flight_id={forms['flight_id']} AND
                depart_dt='{forms['depart_date'] + ' ' + forms['depart_time'] + ':00'}'"""
    tickets = db.execute(query).fetchall()

    if not tickets:
        session['purchase error'] = 'Flight does not exist or is fully booked'
        return redirect(url_for('search'))
    else:
        try:
            query = f"""INSERT INTO purchases VALUES(\
                        '{session['username']}', {tickets[0][0]},
                         {tickets[0][3]}, '{forms['depart_date'] + ' ' + forms['depart_time'] + ':00'}',
                        '{forms['airline']}', NOW(), '{forms['card_type']}', {forms['card_num']},
                        '{forms['card_holder']}', '{forms['card_expir']}')"""
            db.execute(query)
            db.commit()

            session['success'] = "Successfully purchased!"
            return redirect(url_for('search'))
        except Exception as e:
            session['purchase error'] = 'Invalid credit info'
            return redirect(url_for('search'))

@app.route('/cancel', methods=['POST', 'GET'])
def cancel():
    if 'name' not in session or session['role'] == 'staff':
        return redirect(url_for('login'))

    ticket_id = request.form['ticket_id']
    airline = request.form['airline']
    flight_id = request.form['flight_id']
    depart_dt = request.form['depart_date'] + ' ' + request.form['depart_time'] + ':00'
    
    now = datetime.now()
    flight_dt = datetime.strptime(depart_dt, '%Y-%m-%d %H:%M:%S')

    if now > flight_dt - relativedelta(days=1):
        session['cancel_error'] = 'Cannot cancel flight less than 24 hours in advance'
        return redirect(url_for('home'))

    query = f"""DELETE FROM purchases
                WHERE c_email='{session['username']}' AND ticket_id={ticket_id} AND
                    airline='{airline}' AND depart_dt='{depart_dt}'"""

    db.execute(query)
    db.commit()

    return redirect(url_for('home'))

@app.route('/spend-filter', methods=['POST', 'GET'])
def spend_filter():
    if 'name' not in session or session['role'] == 'staff':
        return redirect(url_for('login'))

    start = request.form['start_date']
    end = request.form['end_date']

    if start > end:
        session['spend-filter-error'] = 'Invalid date range'
        return redirect(url_for('home'))

    query = f"""SELECT DATE_TRUNC('month', P.purchase_dt) as month,
                    DATE_TRUNC('year', P.purchase_dt) as year,
                    sum(T.sold_price) as money_spent
                FROM purchases as P NATURAL JOIN ticket as T
                WHERE P.c_email='{session['username']}' 
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

    create_figure(date_range)

    session['spend-filter'] = True
    return redirect(url_for('home'))

@app.route("/comment", methods=['POST', 'GET'])
def comment():
    if 'name' not in session:
        return redirect(url_for('login'))

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
    return render_template('staff_home.html')
