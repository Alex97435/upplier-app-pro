import awsgi
from supplier_app import app as flask_app

# Vercel appelle cette fonction
def handler(event, context):
    return awsgi.response(flask_app, event, context)
