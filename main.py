# -*- encoding: utf-8 -*-
#
# Copyright © 2014 ZhiQiang Fan
#
# Author: ZhiQiang Fan <aji.zqfan@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""`main` is the top level module for your Flask application."""

from __future__ import print_function

import calendar
import datetime
import os

from bs4 import BeautifulSoup
import flask
from flask import request
from google.appengine.api import users
from google.appengine.ext import ndb
import jinja2
import requests


JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

app = flask.Flask(__name__, static_folder='static')
# Note: We don't need to call run() since our application is embedded within
# the App Engine WSGI application server.

class AirQuality(ndb.Model):
    source = ndb.StringProperty()
    station_name = ndb.StringProperty()
    station_type = ndb.StringProperty()
    no2 = ndb.StringProperty()
    o3 = ndb.StringProperty()
    so2 = ndb.StringProperty()
    co = ndb.StringProperty()
    pm10 = ndb.StringProperty()
    pm2_5 = ndb.StringProperty()
    aqhi = ndb.StringProperty()
    publish_timestamp = ndb.DateTimeProperty()
    timestamp = ndb.DateTimeProperty(auto_now_add=True)

def get_air_quality_key(source='hk-aqhi'):
    return ndb.Key("AQHI", source)

@app.route('/')
def get_sample_data():
    key = get_air_quality_key()
    query = AirQuality.query(ancestor=key)
    air_qualities = query.order(-AirQuality.timestamp).fetch(24)
    template = JINJA_ENVIRONMENT.get_template('index.html')
    return template.render({
        'users': users,
        'air_qualities': air_qualities
    })

def _get_latest_data():
    key = get_air_quality_key()
    query = AirQuality.query(ancestor=key)
    air_qualities = query.order(-AirQuality.timestamp).fetch(1)
    return air_qualities[0] if air_qualities else None

@app.route('/flush')
def grab_and_store_data():
    url = 'http://www.aqhi.gov.hk/gt/aqhi/pollutant-and-aqhi-distribution.html'
    resp = requests.get(url)
    soup = BeautifulSoup(resp.content)

    time_text = soup.find(id='distribution_Eng').find('p').text
    publish_timestamp = datetime.datetime.strptime(
        time_text, '(At %Y-%m-%d %H:%M)')

    latest_data = _get_latest_data()
    if latest_data and latest_data.publish_timestamp == publish_timestamp:
        return 'no new data'

    stations = []
    general_stations = soup.find(id='tblDistribution_g')
    for station in general_stations.find_all('tr')[3:]:
        station_data = [0,]
        for data in station.find_all('td'):
            station_data.append(data.string)
        stations.append(station_data)
    roadside_stations = soup.find(id='tblDistribution_r')
    for station in roadside_stations.find_all('tr')[3:]:
        station_data = [1,]
        for data in station.find_all('td'):
            station_data.append(data.string)
        stations.append(station_data)

    air_qualities = []
    for station in stations:
        key = get_air_quality_key()
        air_quality = AirQuality(parent=key)
        air_quality.station_type = ['General', 'Roadside'][station[0]]
        air_quality.station_name = station[1]
        air_quality.no2 = station[2]
        air_quality.o3 = station[3]
        air_quality.so2 = station[4]
        air_quality.co = station[5]
        air_quality.pm10 = station[6]
        air_quality.pm2_5 = station[7]
        air_quality.aqhi = station[8]
        air_quality.publish_timestamp = publish_timestamp
        air_qualities.append(air_quality)

    for air_quality in reversed(air_qualities):
        air_quality.put()
    return str(air_qualities)

@app.route('/charts/stations/<name>')
def get_charts(name):
    valid_users = ['aji.zqfan@gmail.com', 'jennyfzl@gmail.com']
    if users.get_current_user().email() not in valid_users:
        return 'Not Authorized', 401
    name = str(name)
    key = get_air_quality_key()
    query = AirQuality.query(AirQuality.station_name==name, ancestor=key)
    datas = query.order(-AirQuality.timestamp).fetch(24)
    if not datas:
        return "No data for '%s'" % name, 404
    datas.reverse()
    for data in datas:
        if data.co != '-':
            data.co = str(float(data.co)/10)
    template = JINJA_ENVIRONMENT.get_template('charts.html')
    return template.render({'datas': datas, 'station_name': name})

@app.route('/charts/stations/Central/Western')
def _cw_redirect():
    return get_charts('Central/Western')

@app.route('/statistics')
def statistics():
    if users.get_current_user().email() != 'aji.zqfan@gmail.com':
        return 'Not Authorized', 401
    station = request.args.get('station')
    now = datetime.datetime.utcnow()
    year = int(request.args.get('year', now.year))
    month = int(request.args.get('month', now.month))
    start = datetime.datetime(year, month, 1)
    days = calendar.monthrange(year, month)[1]
    end = start + datetime.timedelta(days=days)

    key = get_air_quality_key()
    kwargs = {
        'ancestor': key,
    }
    if station:
        query = AirQuality.query(AirQuality.publish_timestamp>=start,
                                 AirQuality.publish_timestamp<end,
                                 AirQuality.station_name==station,
                                 ancestor=key)
    else:
        query = AirQuality.query(AirQuality.publish_timestamp>=start,
                                 AirQuality.publish_timestamp<end,
                                 ancestor=key)

    datas = query.order(-AirQuality.publish_timestamp,
                        -AirQuality.timestamp).fetch()
    template = JINJA_ENVIRONMENT.get_template('statistics.html')
    return template.render({
        'users': users,
        'air_qualities': datas
    })

@app.route('/js/<path:filename>')
def get_js(filename):
    return flask.send_from_directory(app.static_folder, filename)

@app.errorhandler(404)
def page_not_found(e):
    """Return a custom 404 error."""
    return 'Sorry, Nothing at this URL.', 404

@app.errorhandler(500)
def internal_server_error(e):
    """Return a custom 500 error."""
    return 'Sorry, unexpected error: {}'.format(e), 500
