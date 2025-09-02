#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UMPAY 支付系统 API 服务器
支持 USDT 和 TRX 支付
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import hashlib
import hmac
import time
import json
import os
import sqlite3
import requests
from datetime import datetime, timedelta
from threading import Thread
import schedule
from decimal import Decimal
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

app = Flask(__name__)
CORS(app)

# 配置
class Config:
    SECRET_KEY = os.getenv('UMPAY_SECRET_KEY', 'your-secret-key-here')
    DATABASE = os.getenv('UMPAY_DATABASE', 'umpay.db')
    
    # TronGrid API配置
    TRON_API_KEY = os.getenv('TRON_API_KEY', '')
    TRON_API_URL = 'https://api.trongrid.io'
    
    # 钱包地址配置
    USDT_WALLET_ADDRESS = os.getenv('USDT_WALLET_ADDRESS', '')
    TRX_WALLET_ADDRESS = os.getenv('TRX_WALLET_ADDRESS', '')
    
    # USDT合约地址 (TRC20)
    USDT_CONTRACT_ADDRESS = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
    
    # 订单过期时间（分钟）
    ORDER_EXPIRE_MINUTES = 30
    
    # 确认区块数
    CONFIRMATION_BLOCKS = 1

app.config.from_object(Config)

# 数据库初始化
def init_db():
    conn = sqlite3.connect(app.config['DATABASE'])
    cursor = conn.cursor()
    
    # 创建订单表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            merchant_id TEXT NOT NULL,
            amount TEXT NOT NULL,
            currency TEXT NOT NULL,
            payment_address TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            transaction_hash TEXT,
            callback_url TEXT,
            return_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            confirmed_at TIMESTAMP
        )
    ''')
    
    # 创建交易记录表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            tx_hash TEXT NOT NULL,
            from_address TEXT,
            to_address TEXT,
            amount TEXT,
            currency TEXT,
            block_number INTEGER,
            confirmations INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders (order_id)
        )
    ''')
    
    conn.commit()
    conn.close()

# 工具函数
def generate_signature(data, secret_key):
    """生成签名"""
    # 排序参数
    sorted_params = sorted([(k, v) for k, v in data.items() if k != 'signature'])
    query_string = '&'.join([f"{k}={v}" for k, v in sorted_params])
    
    # 添加密钥
    sign_string = query_string + '&key=' + secret_key
    
    # 生成MD5签名
    return hashlib.md5(sign_string.encode()).hexdigest().upper()

def verify_signature(data, signature, secret_key):
    """验证签名"""
    expected = generate_signature(data, secret_key)
    return hmac.compare_digest(signature, expected)

def generate_payment_address(currency, order_id):
    """生成支付地址（这里使用固定地址，实际应该为每个订单生成唯一地址）"""
    if currency == 'USDT':
        return app.config['USDT_WALLET_ADDRESS']
    elif currency == 'TRX':
        return app.config['TRX_WALLET_ADDRESS']
    else:
        raise ValueError(f"不支持的货币: {currency}")

def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn

# API路由
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
        
        # 生成支付地址
        payment_address = generate_payment_address(data['currency'], data['order_id'])
        
        # 计算过期时间
        expires_at = datetime.now() + timedelta(minutes=app.config['ORDER_EXPIRE_MINUTES'])
        
        # 保存订单到数据库
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO orders (order_id, merchant_id, amount, currency, payment_address, 
                                  callback_url, return_url, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['order_id'],
                data['merchant_id'],
                data['amount'],
                data['currency'],
                payment_address,
                data.get('callback_url'),
                data.get('return_url'),
                expires_at
            ))
            conn.commit()
        except sqlite3.IntegrityError:
            return jsonify({
                'success': False,
                'message': '订单ID已存在'
            }), 400
        finally:
            conn.close()
        
        # 生成二维码（可选）
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM orders WHERE order_id = ?', (data['payment_id'],))
        order = cursor.fetchone()
        conn.close()
        
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
        
        # 这里应该验证webhook的来源
        # 处理交易确认逻辑
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

# 区块链交互函数
def get_tron_account_transactions(address, limit=50):
    """获取TRON账户交易记录"""
    try:
        headers = {}
        if app.config['TRON_API_KEY']:
            headers['TRON-PRO-API-KEY'] = app.config['TRON_API_KEY']
        
        url = f"{app.config['TRON_API_URL']}/v1/accounts/{address}/transactions"
        params = {
            'limit': limit,
            'order_by': 'block_timestamp,desc'
        }
        
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        
        return response.json()
    except Exception as e:
        print(f"获取TRON交易记录失败: {e}")
        return None

def get_trc20_transfers(address, contract_address, limit=50):
    """获取TRC20代币转账记录"""
    try:
        headers = {}
        if app.config['TRON_API_KEY']:
            headers['TRON-PRO-API-KEY'] = app.config['TRON_API_KEY']
        
        url = f"{app.config['TRON_API_URL']}/v1/accounts/{address}/transactions/trc20"
        params = {
            'limit': limit,
            'contract_address': contract_address,
            'order_by': 'block_timestamp,desc'
        }
        
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        
        return response.json()
    except Exception as e:
        print(f"获取TRC20转账记录失败: {e}")
        return None

def check_payment_confirmations():
    """检查支付确认状态"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 获取待确认的订单
        cursor.execute('''
            SELECT * FROM orders 
            WHERE status = 'pending' 
            AND expires_at > datetime('now')
        ''')
        pending_orders = cursor.fetchall()
        
        for order in pending_orders:
            currency = order['currency']
            payment_address = order['payment_address']
            expected_amount = Decimal(order['amount'])
            
            if currency == 'TRX':
                # 检查TRX转账
                transactions = get_tron_account_transactions(payment_address)
                if transactions and 'data' in transactions:
                    for tx in transactions['data']:
                        if tx.get('ret') and tx['ret'][0].get('contractRet') == 'SUCCESS':
                            # 检查转账金额和时间
                            for contract in tx.get('raw_data', {}).get('contract', []):
                                if contract.get('type') == 'TransferContract':
                                    value = contract.get('parameter', {}).get('value', {})
                                    amount = Decimal(value.get('amount', 0)) / 1000000  # TRX精度
                                    
                                    if amount >= expected_amount:
                                        # 更新订单状态
                                        update_order_status(order['order_id'], 'completed', tx['txID'])
                                        send_callback(order, tx['txID'])
                                        break
            
            elif currency == 'USDT':
                # 检查USDT转账
                transfers = get_trc20_transfers(payment_address, app.config['USDT_CONTRACT_ADDRESS'])
                if transfers and 'data' in transfers:
                    for transfer in transfers['data']:
                        if transfer.get('to') == payment_address:
                            amount = Decimal(transfer.get('value', 0)) / 1000000  # USDT精度
                            
                            if amount >= expected_amount:
                                # 更新订单状态
                                update_order_status(order['order_id'], 'completed', transfer['transaction_id'])
                                send_callback(order, transfer['transaction_id'])
                                break
        
        conn.close()
        
    except Exception as e:
        print(f"检查支付确认失败: {e}")

def update_order_status(order_id, status, transaction_hash=None):
    """更新订单状态"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if transaction_hash:
            cursor.execute('''
                UPDATE orders 
                SET status = ?, transaction_hash = ?, confirmed_at = datetime('now')
                WHERE order_id = ?
            ''', (status, transaction_hash, order_id))
        else:
            cursor.execute('''
                UPDATE orders 
                SET status = ?
                WHERE order_id = ?
            ''', (status, order_id))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        print(f"更新订单状态失败: {e}")

def send_callback(order, transaction_hash):
    """发送回调通知"""
    try:
        if not order['callback_url']:
            return
        
        callback_data = {
            'order_id': order['order_id'],
            'status': 'completed',
            'transaction_hash': transaction_hash,
            'amount': order['amount'],
            'currency': order['currency'],
            'timestamp': int(time.time())
        }
        
        # 生成回调签名
        callback_data['signature'] = generate_signature(callback_data, app.config['SECRET_KEY'])
        
        # 发送回调
        response = requests.post(order['callback_url'], json=callback_data, timeout=10)
        response.raise_for_status()
        
        print(f"回调发送成功: {order['order_id']}")
        
    except Exception as e:
        print(f"发送回调失败: {e}")

def expire_old_orders():
    """过期旧订单"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE orders 
            SET status = 'expired'
            WHERE status = 'pending' 
            AND expires_at <= datetime('now')
        ''')
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        print(f"过期订单处理失败: {e}")

# 定时任务
def run_scheduled_tasks():
    """运行定时任务"""
    schedule.every(30).seconds.do(check_payment_confirmations)
    schedule.every(5).minutes.do(expire_old_orders)
    
    while True:
        schedule.run_pending()
        time.sleep(1)

# 根路径路由
@app.route('/', methods=['GET'])
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

# 健康检查
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    })

# 初始化数据库（Vercel部署时需要）
try:
    init_db()
except Exception as e:
    print(f"Database initialization error: {e}")

# Vercel部署需要的应用导出
# 直接导出app实例供Vercel使用

if __name__ == '__main__':
    # 启动定时任务线程（仅在本地运行时）
    task_thread = Thread(target=run_scheduled_tasks, daemon=True)
    task_thread.start()
    
    # 启动Flask应用
    app.run(
        host=os.getenv('UMPAY_HOST', '0.0.0.0'),
        port=int(os.getenv('UMPAY_PORT', 8080)),
        debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    )
