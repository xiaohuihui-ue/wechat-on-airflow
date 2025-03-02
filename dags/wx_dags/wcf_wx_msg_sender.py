#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信消息发送DAG

功能：
1. 接收消息内容和目标接收者
2. 通过WCF API发送消息
3. 支持@群成员

特点：
1. 按需触发执行
2. 最大并发运行数为1
3. 支持发送文本消息
4. 超时时间1分钟
"""

# 标准库导入
import uuid
from datetime import datetime, timedelta

# Airflow相关导入
from airflow import DAG
from airflow.operators.python import PythonOperator

# 自定义库导入
from utils.wechat_channl import send_wx_msg
from utils.wechat_channl import get_wx_contact_list

# 数据库相关导入
from airflow.hooks.base import BaseHook
from airflow.models import Variable

# 微信消息类型定义
WX_MSG_TYPES = {
    0: "朋友圈消息",
    1: "文字",
    3: "图片", 
    34: "语音",
    37: "好友确认",
    40: "POSSIBLEFRIEND_MSG",
    42: "名片",
    43: "视频",
    47: "石头剪刀布 | 表情图片",
    48: "位置",
    49: "共享实时位置、文件、转账、链接",
    50: "VOIPMSG",
    51: "微信初始化",
    52: "VOIPNOTIFY", 
    53: "VOIPINVITE",
    62: "小视频",
    66: "微信红包",
    9999: "SYSNOTICE",
    10000: "红包、系统消息",
    10002: "撤回消息",
    1048625: "搜狗表情",
    16777265: "链接",
    436207665: "微信红包",
    536936497: "红包封面",
    754974769: "视频号视频",
    771751985: "视频号名片",
    822083633: "引用消息",
    922746929: "拍一拍",
    973078577: "视频号直播",
    974127153: "商品链接",
    975175729: "视频号直播",
    1040187441: "音乐链接",
    1090519089: "文件"
}


DAG_ID = "wx_msg_sender"


def get_contact_name(source_ip: str, wxid: str, wx_user_name: str) -> str:
    """
    获取联系人/群名称，使用Airflow Variable缓存联系人列表，1小时刷新一次
    wxid: 可以是sender或roomid
    """

    print(f"获取联系人/群名称, source_ip: {source_ip}, wxid: {wxid}")
    # 获取缓存的联系人列表
    cache_key = f"{wx_user_name}_CONTACT_INFOS"
    current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cached_data = Variable.get(cache_key, default_var={"update_time": "1970-01-01 00:00:00", "contact_infos": {}}, deserialize_json=True)
    
    # 检查是否需要刷新缓存（1小时 = 3600秒）
    cached_time = datetime.strptime(cached_data["update_time"], '%Y-%m-%d %H:%M:%S')
    if (datetime.now() - cached_time).total_seconds() > 3600:
        # 获取最新的联系人列表
        wx_contact_list = get_wx_contact_list(wcf_ip=source_ip)
        print(f"刷新联系人列表缓存，数量: {len(wx_contact_list)}")
        
        # 构建联系人信息字典
        contact_infos = {}
        for contact in wx_contact_list:
            contact_wxid = contact.get('wxid', '')
            contact_infos[contact_wxid] = contact
            
        # 更新缓存和时间戳
        cached_data = {"update_time": current_timestamp, "contact_infos": contact_infos}
        try:
            Variable.set(cache_key, cached_data, serialize_json=True)
        except Exception as error:
            print(f"[WATCHER] 更新缓存失败: {error}")
    else:
        print(f"使用缓存的联系人列表，数量: {len(cached_data['contact_infos'])}", cached_data)

    # 返回联系人名称
    contact_name = cached_data["contact_infos"].get(wxid, {}).get('name', '')

    # 如果联系人名称不存在，则尝试刷新缓存
    if not contact_name:
        # 获取最新的联系人列表
        wx_contact_list = get_wx_contact_list(wcf_ip=source_ip)
        print(f"刷新联系人列表缓存，数量: {len(wx_contact_list)}")
        
        # 构建联系人信息字典
        contact_infos = {}
        for contact in wx_contact_list:
            contact_wxid = contact.get('wxid', '')
            contact_infos[contact_wxid] = contact
            
        # 更新缓存和时间戳
        cached_data = {"update_time": current_timestamp, "contact_infos": contact_infos}
        try:
            Variable.set(cache_key, cached_data, serialize_json=True)
        except Exception as error:
            print(f"[WATCHER] 更新缓存失败: {error}")

        # 重新获取联系人名称
        contact_name = contact_infos.get(wxid, {}).get('name', '')

    print(f"返回联系人名称, wxid: {wxid}, 名称: {contact_name}")
    return contact_name


def send_msg(**context):
    """
    发送微信消息
    
    Args:
        **context: Airflow上下文参数，包含dag_run等信息
    """
    # 输入数据
    input_data = context.get('dag_run').conf
    print(f"输入数据: {input_data}")
    up_for_send_msg = input_data['content']
    source_ip = input_data['source_ip']
    room_id = input_data['roomid']
    aters = input_data.get('aters', '')

    # 发送文本消息
    send_wx_msg(wcf_ip=source_ip, message=up_for_send_msg, receiver=room_id, aters=aters)


def save_msg_to_db(**context):
    """
    保存消息到数据库
    """
    # 获取传入的消息数据
    message_data = context.get('dag_run').conf
    print(f"保存消息到数据库, message_data: {message_data}")
    if not message_data:
        print("[DB_SAVE] 没有收到消息数据")
        return
    
    # 提取消息信息
    room_id = message_data.get('roomid', '')
    sender = message_data.get('sender', '')
    msg_id = message_data.get('id', '') or str(uuid.uuid4())
    msg_type = message_data.get('type', 0)
    content = message_data.get('content', '')
    is_self =  message_data.get('is_self', True)  # 是否群聊
    is_group = message_data.get('is_group', 0)  # 是否群聊
    msg_timestamp = int(datetime.now().timestamp())
    msg_datetime = datetime.now()
    source_ip = message_data.get('source_ip', '')
    
    # 获取微信账号信息
    wx_account_info = context.get('task_instance').xcom_pull(key='wx_account_info')
    if not wx_account_info:
        print("[DB_SAVE] 没有获取到微信账号信息")
        return
    
    wx_user_name = wx_account_info.get('name', '')
    wx_user_id = wx_account_info.get('wxid', '')
    
    # 获取房间和发送者信息
    room_name = get_contact_name(source_ip, room_id, wx_user_name)
    sender_name = get_contact_name(source_ip, sender, wx_user_name) or (wx_user_name if is_self else '')
    
    # 消息类型名称
    msg_type_name = "文字"
      
    # 聊天记录的创建数据包
    create_table_sql = """CREATE TABLE IF NOT EXISTS `wx_chat_records` (
        `id` bigint(20) NOT NULL AUTO_INCREMENT,
        `msg_id` varchar(64) NOT NULL COMMENT '微信消息ID',
        `wx_user_id` varchar(64) NOT NULL COMMENT '微信用户ID',
        `wx_user_name` varchar(64) NOT NULL COMMENT '微信用户名',
        `room_id` varchar(64) NOT NULL COMMENT '聊天室ID',
        `room_name` varchar(128) DEFAULT NULL COMMENT '聊天室名称',
        `sender_id` varchar(64) NOT NULL COMMENT '发送者ID',
        `sender_name` varchar(128) DEFAULT NULL COMMENT '发送者名称',
        `msg_type` int(11) NOT NULL COMMENT '消息类型',
        `msg_type_name` varchar(64) DEFAULT NULL COMMENT '消息类型名称',
        `content` text COMMENT '消息内容',
        `is_self` tinyint(1) DEFAULT '0' COMMENT '是否自己发送',
        `is_group` tinyint(1) DEFAULT '0' COMMENT '是否群聊',
        `source_ip` varchar(64) DEFAULT NULL COMMENT '来源IP',
        `msg_timestamp` bigint(20) DEFAULT NULL COMMENT '消息时间戳',
        `msg_datetime` datetime DEFAULT NULL COMMENT '消息时间',
        `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
        PRIMARY KEY (`id`),
        UNIQUE KEY `uk_msg_id` (`msg_id`),
        KEY `idx_room_id` (`room_id`),
        KEY `idx_sender_id` (`sender_id`),
        KEY `idx_wx_user_id` (`wx_user_id`),
        KEY `idx_msg_datetime` (`msg_datetime`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='微信聊天记录';
    """
    
    # 插入数据SQL
    insert_sql = """INSERT INTO `wx_chat_records` 
    (msg_id, wx_user_id, wx_user_name, room_id, room_name, sender_id, sender_name, 
    msg_type, msg_type_name, content, is_self, is_group, source_ip, msg_timestamp, msg_datetime) 
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE 
    content = VALUES(content),
    room_name = VALUES(room_name),
    sender_name = VALUES(sender_name),
    updated_at = CURRENT_TIMESTAMP
    """
    
    db_conn = None
    cursor = None
    try:
        # 使用get_hook函数获取数据库连接
        db_hook = BaseHook.get_connection("wx_db").get_hook()
        db_conn = db_hook.get_conn()
        cursor = db_conn.cursor()
        
        # 创建表（如果不存在）
        cursor.execute(create_table_sql)
        
        # 插入数据
        cursor.execute(insert_sql, (
            msg_id, 
            wx_user_id,
            wx_user_name,
            room_id,
            room_name,
            sender,
            sender_name,
            msg_type,
            msg_type_name,
            content,
            1 if is_self else 0,
            1 if is_group else 0,
            source_ip,
            msg_timestamp,
            msg_datetime
        ))
        
        # 提交事务
        db_conn.commit()
        print(f"[DB_SAVE] 成功保存消息到数据库: {msg_id}")
    except Exception as e:
        print(f"[DB_SAVE] 保存消息到数据库失败: {e}")
        if db_conn:
            try:
                db_conn.rollback()
            except:
                pass
        raise Exception(f"[DB_SAVE] 保存消息到数据库失败, 稍后重试")
    finally:
        # 关闭连接
        if cursor:
            try:
                cursor.close()
            except:
                pass
        if db_conn:
            try:
                db_conn.close()
            except:
                pass

# 创建DAG
dag = DAG(
    dag_id=DAG_ID,
    default_args={'owner': 'claude89757'},
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    max_active_runs=50,
    catchup=False,
    tags=['个人微信'],
    description='个人微信消息发送',
)

# 创建处理消息的任务
send_msg_task = PythonOperator(
    task_id='send_msg',
    python_callable=send_msg,
    provide_context=True,
    dag=dag
)

save_msg_to_db_task = PythonOperator(
    task_id='save_msg_to_db',
    python_callable=save_msg_to_db,
    provide_context=True,
    retries=5,
    retry_delay=timedelta(seconds=1),
    dag=dag
)

send_msg_task >> save_msg_to_db_task
