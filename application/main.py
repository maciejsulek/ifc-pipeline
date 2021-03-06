##################################################################################
#                                                                                #
# Copyright (c) 2020 AECgeeks                                                    #
#                                                                                #
# Permission is hereby granted, free of charge, to any person obtaining a copy   #
# of this software and associated documentation files (the "Software"), to deal  #
# in the Software without restriction, including without limitation the rights   #
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell      #
# copies of the Software, and to permit persons to whom the Software is          #
# furnished to do so, subject to the following conditions:                       #
#                                                                                #
# The above copyright notice and this permission notice shall be included in all #
# copies or substantial portions of the Software.                                #
#                                                                                #
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR     #
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,       #
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE    #
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER         #
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,  #
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE  #
# SOFTWARE.                                                                      #
#                                                                                #
##################################################################################

from __future__ import print_function

import os
import threading

from collections import defaultdict
from flask_dropzone import Dropzone

from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, request, send_file, render_template, abort, jsonify, redirect, url_for
from flask_cors import CORS
from flask_basicauth import BasicAuth
from flasgger import Swagger

import utils
import worker
import database

application = Flask(__name__)
dropzone = Dropzone(application)

# application.config['DROPZONE_UPLOAD_MULTIPLE'] = True
# application.config['DROPZONE_PARALLEL_UPLOADS'] = 3

DEVELOPMENT = os.environ.get('environment', 'production').lower() == 'development'

if not DEVELOPMENT:
    # In some setups this proved to be necessary for url_for() to pick up HTTPS
    application.wsgi_app = ProxyFix(application.wsgi_app, x_proto=1)

CORS(application)
application.config['SWAGGER'] = {
    'title': os.environ.get('APP_NAME', 'ifc-pipeline request API'),
    'openapi': '3.0.2',
    "specs": [
        {
            "version": "0.1",
            "title": os.environ.get('APP_NAME', 'ifc-pipeline request API'),
            "description": os.environ.get('APP_NAME', 'ifc-pipeline request API'),
            "endpoint": "spec",
            "route": "/apispec",
        },
    ]
}
swagger = Swagger(application)

if not DEVELOPMENT:
    from redis import Redis
    from rq import Queue

    q = Queue(connection=Redis(host=os.environ.get("REDIS_HOST", "localhost")))


@application.route('/', methods=['GET'])
def get_main():
    return render_template('index.html')



def process_upload(filewriter, callback_url=None):
    id = utils.generate_id()
    d = utils.storage_dir_for_id(id)
    os.makedirs(d)
    
    filewriter(os.path.join(d, id+".ifc"))
    
    session = database.Session()
    session.add(database.model(id, ''))
    session.commit()
    session.close()
    
    if DEVELOPMENT:
        t = threading.Thread(target=lambda: worker.process(id, callback_url))
        t.start()

        
    else:
        q.enqueue(worker.process, id, callback_url)

    return id
    


def process_upload_multiple(files, callback_url=None):
    id = utils.generate_id()
    d = utils.storage_dir_for_id(id)
    os.makedirs(d)
   
    file_id = 0
    session = database.Session()
    m = database.model(id, '')   
    session.add(m)
  
    for file in files:
        fn = file.filename
        filewriter = lambda fn: file.save(fn)
        filewriter(os.path.join(d, id+"_"+str(file_id)+".ifc"))
        file_id += 1
        
        m.files.append(database.file(id, ''))
    
    session.commit()

    
    session.close()
    
    if DEVELOPMENT:
        t = threading.Thread(target=lambda: worker.process_multiple(id, callback_url))
        t.start()
        
      
        
    else:
        q.enqueue(worker.process_multiple, id, callback_url)


    return id



@application.route('/', methods=['POST'])
def put_main():
    """
    Upload model
    ---
    requestBody:
      content:
        multipart/form-data:
          schema:
            type: object
            properties:
              ifc:
                type: string
                format: binary
    responses:
      '200':
        description: redirect
    """
    ids = []
   
    files = []
    for key, f in request.files.items():
        if key.startswith('file'):
            file = f
            files.append(file)    

       
    id = process_upload_multiple(files)
    url = url_for('check_viewer', id=id)

  

    if request.accept_mimetypes.accept_json:

       return jsonify({"url":url})

    else:

        return redirect(url)

 


@application.route('/p/<id>', methods=['GET'])
def check_viewer(id):
    if not utils.validate_id(id):
        abort(404)
    return render_template('progress.html', id=id)    
    
    
@application.route('/pp/<id>', methods=['GET'])
def get_progress(id):
    if not utils.validate_id(id):
        abort(404)
    session = database.Session()
    model = session.query(database.model).filter(database.model.code == id).all()[0]
    return jsonify({"progress": model.progress})


@application.route('/v/<id>', methods=['GET'])
def get_viewer(id):
    if not utils.validate_id(id):
        abort(404)
    d = utils.storage_dir_for_id(id)
    n_files = len([name for name in os.listdir(d) if os.path.isfile(os.path.join(d, name)) and os.path.join(d, name).endswith('.ifc') ])
    

    for i in range(n_files):
        glbfn = os.path.join(utils.storage_dir_for_id(id), id + "_" + str(i) + ".glb")
        if not os.path.exists(glbfn):
            abort(404)
                    
    return render_template('viewer.html', **locals())


@application.route('/m/<fn>', methods=['GET'])
def get_model(fn):
    """
    Get model component
    ---
    parameters:
        - in: path
          name: fn
          required: true
          schema:
              type: string
          description: Model id and part extension
          example: BSESzzACOXGTedPLzNiNklHZjdJAxTGT.glb
    """
    
 
    id, ext = fn.split('.', 1)
    
    if not utils.validate_id(id[:-2]):
        abort(404)
  
    if ext not in {"xml", "svg", "glb"}:
        abort(404)
        
   
    path = utils.storage_file_for_id_multiple(id,ext)

    

    if not os.path.exists(path):
        abort(404)
        
   
    return send_file(path)

"""
# Create a file called routes.py with the following
# example content to add application-specific routes

from main import application

@application.route('/test', methods=['GET'])
def test_hello_world():
    return 'Hello world'
"""
try:
    import routes
except ImportError as e:
    pass
