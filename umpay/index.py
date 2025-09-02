from flask import Flask, request, jsonify
from flask_cors import CORS
import hashlib
import hmac
import time
import os
from datetime import datetime, timedelta
import requests
from decimal import Decimal

app = Flask(__name__)
CORS(app)

# 配置
class Config:
    SECRET_KEY = os.getenv('UMPAY_SECRET_KEY', 'your-secret-key-here')
    TRON_API_KEY = os.getenv('TRON_API_KEY', '')
    TRON_API_URL = 'https://api.trongrid.io'
    USDT_WALLET_ADDRESS = os.getenv('USDT_WALLET_ADDRESS', '')
    TRX_WALLET_ADDRESS = os.getenv('TRX_WALLET_ADDRESS', '')
    USDT_CONTRACT_ADDRESS = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
    ORDER_EXPIRE_MINUTES = 30

app.config.from_object(Config)

# 内存存储（临时方案，生产环境需要使用数据库）
orders = {}
transactions = {}

# 工具函数
def generate_signature(data, secret_key):
    """生成签名"""
    sorted_params = sorted([(k, v) for k, v in data.items() if k != 'signature'])
    query_string = '&'.join([f"{k}={v}" for k, v in sorted_params])
    sign_string = query_string + '&key=' + secret_key
    return hashlib.md5(sign_string.encode()).hexdigest().upper()

def verify_signature(data, signature, secret_key):
    """验证签名"""
    expected = generate_signature(data, secret_key)
    return hmac.compare_digest(signature, expected)

def generate_payment_address(currency, order_id):
    """生成支付地址"""
    if currency == 'USDT':
        return app.config['USDT_WALLET_ADDRESS']
    elif currency == 'TRX':
        return app.config['TRX_WALLET_ADDRESS']
    else:
        raise ValueError(f"不支持的货币: {currency}")

@app.route('/')
def index():
    return jsonify({
        'service': 'UMPAY Payment System',
        'version': '1.0.0',
        'status': 'running',
        'endpoints': {
            'health': '/health',
            'create_order': '/api/create_order',
            'query_order': '/api/query_order',
            'webhook': '/api/webhook'
        }
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })

@app.route('/api/create_order', methods=['POST'])
def create_order():
    """创建支付订单"""
    try:
        data = request.get_json()
        
        # 验证必需参数
        required_fields = ['merchant_id', 'order_id', 'amount', 'currency']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'message': f'缺少必需参数: {field}'
                }), 400
        
        # 验证签名
        if 'signature' not in data:
            return jsonify({
                'success': False,
                'message': '缺少签名'
            }), 400
        
        signature = data.pop('signature')
        if not verify_signature(data, signature, app.config['SECRET_KEY']):
            return jsonify({
                'success': False,
                'message': '签名验证失败'
            }), 401
        
        # 验证货币类型
        if data['currency'] not in ['USDT', 'TRX']:
            return jsonify({
                'success': False,
                'message': '不支持的货币类型'
            }), 400
        
        # 检查订单是否已存在
        if data['order_id'] in orders:
            return jsonify({
                'success': False,
                'message': '订单ID已存在'
            }), 400
        
        # 生成支付地址
        payment_address = generate_payment_address(data['currency'], data['order_id'])
        
        # 计算过期时间
        expires_at = datetime.now() + timedelta(minutes=app.config['ORDER_EXPIRE_MINUTES'])
        
        # 保存订单到内存
        order = {
            'order_id': data['order_id'],
            'merchant_id': data['merchant_id'],
            'amount': data['amount'],
            'currency': data['currency'],
            'payment_address': payment_address,
            'status': 'pending',
            'transaction_hash': None,
            'callback_url': data.get('callback_url'),
            'return_url': data.get('return_url'),
            'created_at': datetime.now().isoformat(),
            'expires_at': expires_at.isoformat(),
            'confirmed_at': None
        }
        orders[data['order_id']] = order
        
        # 生成二维码URL
        qr_code_url = None
        if data['currency'] == 'USDT':
            qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=tron:{payment_address}?amount={data['amount']}&token=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        elif data['currency'] == 'TRX':
            qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=tron:{payment_address}?amount={data['amount']}"
        
        return jsonify({
            'success': True,
            'payment_id': data['order_id'],
            'payment_address': payment_address,
            'amount': data['amount'],
            'currency': data['currency'],
            'qr_code': qr_code_url,
            'expires_at': expires_at.isoformat()
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/api/query_order', methods=['POST'])
def query_order():
    """查询订单状态"""
    try:
        data = request.get_json()
        
        # 验证必需参数
        if 'payment_id' not in data:
            return jsonify({
                'success': False,
                'message': '缺少payment_id参数'
            }), 400
        
        # 验证签名
        if 'signature' not in data:
            return jsonify({
                'success': False,
                'message': '缺少签名'
            }), 400
        
        signature = data.pop('signature')
        if not verify_signature(data, signature, app.config['SECRET_KEY']):
            return jsonify({
                'success': False,
                'message': '签名验证失败'
            }), 401
        
        # 查询订单
        order = orders.get(data['payment_id'])
        if not order:
            return jsonify({
                'success': False,
                'message': '订单不存在'
            }), 404
        
        return jsonify({
            'success': True,
            'status': order['status'],
            'transaction_hash': order['transaction_hash'],
            'amount': order['amount'],
            'currency': order['currency'],
            'created_at': order['created_at'],
            'confirmed_at': order['confirmed_at']
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/api/webhook', methods=['POST'])
def webhook():
    """接收区块链交易通知"""
    try:
        data = request.get_json()
        # 这里可以处理来自区块链监控服务的通知
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/api/orders', methods=['GET'])
def list_orders():
    """列出所有订单（调试用）"""
    return jsonify({
        'success': True,
        'orders': list(orders.values())
    })

if __name__ == '__main__':
    app.run(debug=True)
