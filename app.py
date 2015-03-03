from flask import Flask, render_template,request,session, redirect, url_for
from flask.ext.socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
from random import randint
import shelve

app = Flask(__name__)
app.secret_key = 'pbnIXrWpH3ppN9itmDU9'
socketio = SocketIO(app)

class defdict(dict):
    def __init__(self, factory):
        self.factory = factory
    def __missing__(self, key):
        self[key] = self.factory(key)
        return self[key]

rooms_info = defdict(lambda name: {'users': defdict(lambda name: {'last': datetime.now(),
                                   'first': datetime.now(),
                                   'name': name}),
    							'video': {'url':'', 'playing_now':False, 'likes':[]},
    							'messages': [],
    							'presentation': {'original_data':[], 'data':[], 'playing_now':0, 'likes':[]},
    							'name': name
								})
"""room(directory) 
        -> 'users' : array
        -> 'playing_now : string' 
        -> 'video_links' : array
        -> 'last_request' : dict(user:time)
        -> online : array
        -> offline : array
        -> messages : array of dicts {sender, text, time}
        -> ice_candidates : dict {username:candidate}"""
rooms_sync={}

@app.route('/', defaults={'room': ''})
@app.route('/<room>')
def index(room):
    return render_template('index.html', room=room)

@app.route('/', methods=["POST"])
def index_post():
    username = request.form ['username']
    room = str(request.form ['roomname'])
    session['room'] = room
    session['username'] = username
    return redirect(url_for('show_room', name=room))

@app.route('/room/<name>')
def show_room(name):
    room = str(name)
    if 'username' not in session:
        return redirect(url_for('index', room=room))
    user = session['username']
    return render_template('room.html', user=user, room=rooms_info[room])

@socketio.on('link')
def room(video_link):
    room = session['room']
    user = session['username']
    rooms_info[room]['video'] = {'url':video_link, 'playing_now':True, 'likes': []}
    rooms_info[room]['presentation']['playing_now']=-rooms_info[room]['presentation']['playing_now']
    emit('linkmp4', video_link, room=room)

threshold_for_offline = 10

def prepare_users_table(room):
    current_time = datetime.now()
    rooms_info[room]['online'] = []
    rooms_info[room]['offline'] = []
    for u in rooms_info[room]['users'].values():
        if(current_time - u['last']).total_seconds()>threshold_for_offline:
            rooms_info[room]['offline'].append(u['name'])
        else:
            rooms_info[room]['online'].append(u['name'])
    rooms_info[room]['online'].sort(key=lambda name: rooms_info[room]['users'][name]['first'])
    rooms_info[room]['offline'].sort(key=lambda name: rooms_info[room]['users'][name]['first'])

@socketio.on('join')
def on_join(data):
    user = data['user']
    room = data['room']
    join_room(room)
    if room not in rooms_sync:
        rooms_sync[room]={'signature':-1, 
            'times':[], 'last_action_time':datetime.now(), 'video_state':False}
    rooms_info[room]['users'][user]['last'] = datetime.now()
    prepare_users_table(room)
    emit('information_for_new_user', rooms_info[room])
    emit('video_likes', rooms_info[room]['video']['likes'])
    emit('pres_likes', rooms_info[room]['presentation']['likes'])

@socketio.on('update_table')
def update_users_table(data):
    user=data['user']
    room = data['room']
    rooms_info[room]['users'][user]['last']=datetime.now()
    prepare_users_table(room)
    # print rooms_info
    emit('users_table', {'offline':rooms_info[room]['offline'], 'online':rooms_info[room]['online']}, room=room)

@socketio.on('pause')
def on_pause(data):
    user = data['user']
    room = data['room']
    time = data['time']
    current_time=datetime.now()
    rooms_info[room]['users'][user]['last'] = current_time
    rooms_sync[room]['last_action_time']=current_time
    rooms_sync[room]['video_state']=False
    emit('need_to_sync', {'time': time, 'vstate':rooms_sync[room]['video_state']}, room=room)

@socketio.on('play')
def on_play(data):
    user = data['user']
    room = data['room']
    time = data['time']
    current_time=datetime.now()
    rooms_info[room]['users'][user]['last'] = current_time
    rooms_sync[room]['last_action_time']=current_time
    rooms_sync[room]['video_state']=True
    emit('need_to_sync', {'time': time, 'vstate':rooms_sync[room]['video_state']}, room=room)

threshold=5

@socketio.on('want_to_sync')
def want_to_sync(data):
    room = data['room']
    user = data['user']
    current_time = datetime.now()
    rooms_info[room]['users'][user]['last'] = current_time
    elapsed_time = current_time - rooms_sync[room]['last_action_time']
    rooms_sync[room]['signature'] = randint(1, 1000000)
    rooms_sync[room]['times'] = []
    # print 'want_to_sync', data
    # print 'want_to_sync', rooms_sync
    # print user+' wants to sync', 'signature ',rooms_sync[room]['signature']
    if elapsed_time.total_seconds()>threshold:
        emit('sync', rooms_sync[room]['signature'], room=room)
        rooms_sync[room]['last_action_time']=datetime.now()
    # print 'want_to_sync',rooms_sync

threshold2=0.1
@socketio.on('need_to_sync')
def need_to_sync(data):
    sign = data['sign']
    time = data['video_time']
    room = data['room']

    if sign == rooms_sync[room]['signature']:
        rooms_sync[room]['times'].append(time)
        if len(rooms_sync[room]['times']) == len(rooms_info[room]['online']):
            maxtime = max(rooms_sync[room]['times'])
            mintime = min(rooms_sync[room]['times'])
            if abs(maxtime-mintime)>threshold2:
                emit('need_to_sync', 
                    {'time': maxtime, 'vstate':rooms_sync[room]['video_state']},
                    room=room)

@socketio.on('like_video')
def like_video(time):
    room = session['room']
    user = session['username']
    rooms_info[room]['video']['likes'].append((user, time))
    emit('video_likes', rooms_info[room]['video']['likes'], room=room)

@socketio.on('like_pres')
def like_pres(index):
    room = session['room']
    user = session['username']
    rooms_info[room]['presentation']['likes'].append((user, index))
    emit('pres_likes', rooms_info[room]['presentation']['likes'], room=room)

@socketio.on('new_msg_from_client')
def get_new_msg(data):
    sender = data['sender']
    text = data['text']
    room = data['room']
    time = datetime.utcnow()
    rooms_info[room]['messages'].append({'sender':sender, 'text':text, 'time':time})
    emit('new_msg_from_server', rooms_info[room]['messages'][-1], room=room)

@socketio.on('initialize_videochat')
def initialize_videochat(data):
    room = session['room']
    print data
    emit('videochat_initialization', data, room=room)  

@socketio.on('presentation_to_server')
def presentation(presentation):
    room = session['room']
    rooms_info[room]['presentation']={'original_data':presentation['data'], 'data':presentation['data'], 'playing_now':1, 'likes':[]}
    rooms_info[room]['video']['playing_now']=False
    emit ('presentation_to_clients', presentation, room=room)

@socketio.on('update_presentation')
def update_presentation(index):
    room = session['room']
    rooms_info[room]['presentation']['playing_now']=int(index)
    rooms_info[room]['video']['playing_now']=False
    print index
    emit('update_presentation', index, room=room)

@socketio.on('change_type')
def change_type(type):
    room=session['room']
    if type=='presentation':
        rooms_info[room]['video']['playing_now']=False
        rooms_info[room]['presentation']['playing_now']=abs(rooms_info[room]['presentation']['playing_now'])
    else:
        rooms_info[room]['video']['playing_now']=True
        rooms_info[room]['presentation']['playing_now']=-abs(rooms_info[room]['presentation']['playing_now'])
    emit ('change_type', type, room=room)

@socketio.on('update_current_image')
def update_current_image (data):
    room = session['room']
    rooms_info[room]['presentation']['data']=data['dataURL']
    emit ('update_current_image', {'dataURL':data['dataURL']}, room=room)

@socketio.on('clear_canvas')
def clear_canvas():
    room = session['room']
    rooms_info[room]['presentation']['data']=rooms_info[room]['presentation']['original_data']
    emit ('update_current_image', {'dataURL':rooms_info[room]['presentation']['data']}, room=room)
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0')