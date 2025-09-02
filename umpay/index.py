from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({
        'service': 'UMPAY Payment System',
        'version': '1.0.0',
        'status': 'running',
        'message': 'Hello from Vercel!'
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': '2024-01-01T00:00:00Z'
    })

if __name__ == '__main__':
    app.run(debug=True)