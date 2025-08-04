import os
import logging
import re
from dotenv import load_dotenv
from openai import OpenAI
from flask import Flask, render_template, request, jsonify, Response
import threading
import webbrowser
import json
import time
import base64
import requests
import tempfile
import mimetypes
import uuid
import hashlib
import socket
from contextlib import closing

app = Flask(__name__)

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 加载环境变量
load_dotenv(os.path.join(os.path.expanduser('~'), '.openai_env'))

# 配置OpenAI客户端
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://www.sophnet.com/api/open-apis/v1"
)

# 从环境变量获取项目ID和EasyLLM ID
SOPHNET_PROJECT_ID = os.getenv("SOPHNET_PROJECT_ID")
DOC_PARSE_EASYLLM_ID = os.getenv("DOC_PARSE_EASYLLM_ID")
IMAGE_OCR_EASYLLM_ID = os.getenv("IMAGE_OCR_EASYLLM_ID")

# 支持的文件类型
SUPPORTED_DOC_TYPES = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.txt', '.pptx']
SUPPORTED_IMAGE_TYPES = ['.jpg', '.jpeg', '.png', '.bmp', '.gif']

# 存储对话历史和状态
conversations = {}

# 默认设置值
DEFAULT_SETTINGS = {
    "model": "DeepSeek-V3-Fast:1xh4CuJsBMrlAvdLBAZYfC",
    "system_prompt": "你是专属智能助手，负责回答用户的任何问题，分析用户提供的文件和图片内容。",
    "max_tokens": 16384
}

def find_free_port(start_port=5000, end_port=5050):
    """在指定范围内查找可用端口"""
    for port in range(start_port, end_port + 1):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            try:
                sock.bind(('localhost', port))
                return port
            except OSError:
                continue
    return None  # 如果没有找到可用端口

def get_conversation(session_id):
    """获取或创建对话历史"""
    if session_id not in conversations:
        print(f"[Server] Creating new conversation: {session_id}")
        conversations[session_id] = {
            "id": session_id,
            "title": "新会话",
            "messages": [
                {"role": "system", "content": DEFAULT_SETTINGS["system_prompt"]}
            ],
            "files": {},  # 确保初始化为字典
            "settings": DEFAULT_SETTINGS.copy(),  # 使用默认设置
            "createdAt": time.time(),
            "starred": False
        }
    else:
        print(f"[Server] Using existing conversation: {session_id}")
    
    return conversations[session_id]

def extract_file_references(text):
    """从文本中提取文件引用 (文件1, 文件A等)"""
    pattern = r'文件(\d+)'
    return re.findall(pattern, text)

def get_file_by_short_id(conversation, short_id):
    """通过短ID获取文件信息"""
    for file_info in conversation['files'].values():
        if file_info['short_id'] == int(short_id):
            return file_info
    return None

def generate_file_context(files):
    """生成文件上下文字符串"""
    context = []
    for file_info in files:
        content_preview = file_info['content'][:1000] + ('...' if len(file_info['content']) > 1000 else '')
        context.append(f"文件{file_info['short_id']} ({file_info['filename']}):\n{content_preview}")
    return "\n\n".join(context)

def parse_document(file_path, original_filename):
    """解析文档为Markdown文本"""
    # 使用原始文件名获取扩展名
    ext = os.path.splitext(original_filename)[1].lower()
    if ext not in SUPPORTED_DOC_TYPES:
        return {"error": f"不支持的文件类型: {ext}，支持的文件类型: {', '.join(SUPPORTED_DOC_TYPES)}"}
    
    # API端点
    url = f"https://www.sophnet.com/api/open-apis/projects/{SOPHNET_PROJECT_ID}/easyllms/doc-parse"
    headers = {"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"}
    
    try:
        with open(file_path, 'rb') as f:
            # 正确构造文件上传请求
            files = {
                'file': (original_filename, f, mimetypes.guess_type(original_filename)[0] or 'application/octet-stream')
            }
            data = {'easyllm_id': DOC_PARSE_EASYLLM_ID}
            
            response = requests.post(url, headers=headers, files=files, data=data)
        
        logging.info(f"文档解析API响应: {response.status_code} - {response.text[:200]}")
        
        if response.status_code == 200:
            result = response.json()
            if 'data' in result:
                return {
                    "success": True, 
                    "content": result['data'], 
                    "filename": original_filename
                }
            else:
                return {"error": f"API返回的数据结构不正确: {response.text}"}
        else:
            return {"error": f"文档解析失败: {response.status_code} - {response.text}"}
    except requests.exceptions.RequestException as e:
        logging.error(f"文档解析请求失败: {str(e)}")
        return {"error": f"文档解析请求失败: {str(e)}"}
    except Exception as e:
        logging.error(f"文档解析过程中出错: {str(e)}")
        return {"error": f"文档解析过程中出错: {str(e)}"}

def image_ocr(image_data, original_filename):
    """识别图片中的文字"""
    # 检查文件扩展名
    ext = os.path.splitext(original_filename)[1].lower()
    if ext not in SUPPORTED_IMAGE_TYPES:
        return {"error": f"不支持的图片格式: {ext}，支持的格式: {', '.join(SUPPORTED_IMAGE_TYPES)}"}
    
    # API端点
    url = f"https://www.sophnet.com/api/open-apis/projects/{SOPHNET_PROJECT_ID}/easyllms/image-ocr"
    
    try:
        headers = {
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
            "Content-Type": "application/json"
        }
        
        # 将图片转换为base64
        base64_image = base64.b64encode(image_data).decode('utf-8')
        
        # 根据文件类型设置正确的MIME类型
        mime_type = mimetypes.guess_type(original_filename)[0] or 'image/jpeg'
        if 'image' not in mime_type:
            mime_type = 'image/jpeg'  # 默认使用JPEG
        
        payload = {
            "easyllm_id": IMAGE_OCR_EASYLLM_ID,
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{base64_image}"
            },
            "use_doc_ori": 1,
            "use_table": 1,
            "use_html_out": 1
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        logging.info(f"图片OCR API响应: {response.status_code} - {response.text[:500]}")
        
        if response.status_code == 200:
            result = response.json()
            if 'result' in result and isinstance(result['result'], list):
                texts = [item['texts'] for item in result['result'] if 'texts' in item]
                return {
                    "success": True, 
                    "text": "\n".join(texts), 
                    "filename": original_filename
                }
            else:
                return {"error": f"OCR返回了未知的数据结构: {response.text}"}
        else:
            return {"error": f"图片识别失败: {response.status_code} - {response.text}"}
    except requests.exceptions.RequestException as e:
        logging.error(f"图片识别请求失败: {str(e)}")
        return {"error": f"图片识别请求失败: {str(e)}"}
    except Exception as e:
        logging.error(f"图片识别过程中出错: {str(e)}")
        return {"error": f"图片识别过程中出错: {str(e)}"}

@app.route('/')
def home():
    """主页面路由"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def handle_upload():
    session_id = request.form.get('session_id', 'default')
    file_type = request.form.get('type')
    
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': '未选择文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': '未选择文件'}), 400
    
    return process_file(file, session_id, file_type)

@app.route('/upload-multi', methods=['POST'])
def handle_multi_upload():
    session_id = request.form.get('session_id', 'default')
    
    if 'files[]' not in request.files:
        return jsonify({'status': 'error', 'message': '未选择文件'}), 400
    
    files = request.files.getlist('files[]')
    if not files:
        return jsonify({'status': 'error', 'message': '未选择文件'}), 400
    
    results = []
    for file in files:
        if file.filename == '':
            continue
            
        # 自动判断文件类型
        ext = os.path.splitext(file.filename)[1].lower()
        file_type = 'document' if ext in SUPPORTED_DOC_TYPES else 'image'
        
        result = process_file(file, session_id, file_type)
        results.append(json.loads(result.data))
    
    return jsonify({
        'status': 'success',
        'message': f'成功处理 {len(results)} 个文件',
        'files': results
    })

def process_file(file, session_id, file_type):
    """处理单个文件并返回结果"""
    # 获取文件扩展名
    ext = os.path.splitext(file.filename)[1].lower()
    original_filename = file.filename
    
    # 检查文件类型
    if file_type == 'document' and ext not in SUPPORTED_DOC_TYPES:
        return jsonify({
            'status': 'error',
            'message': f"不支持的文件类型: {ext}",
            'supported': SUPPORTED_DOC_TYPES
        }), 400
    
    if file_type == 'image' and ext not in SUPPORTED_IMAGE_TYPES:
        return jsonify({
            'status': 'error',
            'message': f"不支持的图片格式: {ext}",
            'supported': SUPPORTED_IMAGE_TYPES
        }), 400
    
    # 创建临时文件
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        file.save(temp_file.name)
        temp_path = temp_file.name
    
    try:
        logging.info(f"开始处理文件: {original_filename} ({file_type})")
        
        # 处理文件
        if file_type == 'document':
            result = parse_document(temp_path, original_filename)
        elif file_type == 'image':
            with open(temp_path, 'rb') as f:
                result = image_ocr(f.read(), original_filename)
        else:
            return jsonify({'status': 'error', 'message': '不支持的格式'}), 400
        
        # 检查处理结果
        if 'error' in result:
            logging.error(f"文件处理失败: {result['error']}")
            return jsonify({
                'status': 'error',
                'filename': original_filename,
                'message': result['error']
            }), 400
        
        logging.info(f"文件处理完成: {original_filename}")
            
        # 获取对话上下文
        conversation = get_conversation(session_id)
        
        # 生成文件ID
        file_id = hashlib.md5(f"{session_id}{original_filename}{time.time()}".encode()).hexdigest()[:12]
        short_id = len(conversation['files']) + 1
        
        # 创建内容预览
        content = result.get('content', result.get('text', ''))
        content_preview = content[:500] + ('...' if len(content) > 500 else '')
        
        # 添加文件到对话上下文
        file_info = {
            "type": file_type,
            "filename": original_filename,
            "content": content,
            "content_preview": content_preview,
            "file_id": file_id,
            "short_id": short_id,
            "display_id": f"文件{short_id}",
            "upload_time": time.time(),
            "preview_html": generate_file_preview_html({
                "type": file_type,
                "filename": original_filename,
                "content_preview": content_preview,
                "display_id": f"文件{short_id}"
            })
        }
        
        conversation['files'][file_id] = file_info
        conversation['lastActive'] = time.time()
        
        # 添加到会话历史
        conversation['messages'].append({
            "role": "user",
            "content": f"上传了{file_type}文件: {original_filename} (ID: {file_info['display_id']})",
            "is_file": True,
            "file_info": file_info
        })
        
        # 返回成功消息
        return jsonify({
            'status': 'success',
            'filename': original_filename,
            'message': f"{'文档' if file_type == 'document' else '图片'}解析成功！",
            'file_type': file_type,
            'content_preview': content_preview,
            'file_id': file_id,
            'short_id': short_id,
            'display_id': file_info['display_id'],
            'preview_html': file_info['preview_html']
        })
        
    except Exception as e:
        logging.error(f"文件处理失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'filename': original_filename,
            'message': f'处理失败: {str(e)}'
        }), 500
    finally:
        # 删除临时文件
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as e:
                logging.warning(f"删除临时文件失败: {str(e)}")

@app.route('/remove-file/<file_id>', methods=['DELETE'])
def remove_file(file_id):
    """从会话中移除文件"""
    session_id = request.args.get('session_id', 'default')
    print(f"[Server] DELETE /remove-file/{file_id}?session_id={session_id}")
    
    conversation = get_conversation(session_id)
    
    # 打印所有文件ID以便调试
    print(f"[Server] All files in session: {list(conversation['files'].keys())}")
    
    # 确保文件存在
    if file_id in conversation['files']:
        file_info = conversation['files'][file_id]
        print(f"[Server] Removing file: {file_info['filename']} (ID: {file_info['display_id']})")
        
        # 记录移除操作
        conversation['messages'].append({
            "role": "system",
            "content": f"用户移除了文件: {file_info['filename']} (ID: {file_info['display_id']})"
        })
        
        # 从会话中移除文件
        del conversation['files'][file_id]
        conversation['lastActive'] = time.time()
        
        # 打印移除后的文件列表
        print(f"[Server] Files after removal: {list(conversation['files'].keys())}")
        
        # 返回成功消息
        return jsonify({
            'status': 'success',
            'message': f"文件 {file_info['display_id']} 已移除",
            'filename': file_info['filename'],
            'display_id': file_info['display_id'],
            'file_id': file_id
        })
    
    # 文件不存在时返回错误
    error_msg = f'文件不存在: {file_id}'
    print(f"[Server] {error_msg}")
    return jsonify({
        'status': 'error',
        'message': error_msg
    }), 404

@app.route('/chat', methods=['POST'])
def chat():
    """处理聊天请求（逐字流式响应）"""
    data = request.json
    session_id = data.get('session_id', 'default')
    user_input = data['message'].strip()
    
    # 获取设置参数（前端传递）
    model = data.get('model', DEFAULT_SETTINGS["model"])
    system_prompt = data.get('system_prompt', DEFAULT_SETTINGS["system_prompt"])
    max_tokens = data.get('max_tokens', DEFAULT_SETTINGS["max_tokens"])
    
    # 验证max_tokens范围
    max_tokens = max(256, min(int(max_tokens), 16384))
    
    if not user_input:
        return jsonify({'error': '消息内容不能为空'}), 400
    
    # 获取对话上下文
    conversation = get_conversation(session_id)
    conversation['lastActive'] = time.time()
    
    # 保存设置到会话
    conversation['settings'] = {
        "model": model,
        "system_prompt": system_prompt,
        "max_tokens": max_tokens
    }
    
    # 准备聊天消息
    chat_messages = []
    
    # 添加系统提示（使用用户设置）
    chat_messages.append({
        "role": "system",
        "content": system_prompt
    })
    
    # 添加文件上下文
    referenced_files = []
    file_references = extract_file_references(user_input)
    
    if file_references:
        for file_ref in file_references:
            file_info = get_file_by_short_id(conversation, file_ref)
            if file_info:
                referenced_files.append(file_info)
    
    # 添加被引用的文件内容
    if referenced_files:
        file_context = generate_file_context(referenced_files)
        chat_messages.append({
            "role": "system",
            "content": f"用户引用了以下文件内容:\n{file_context}"
        })
    
    # 添加历史消息（排除系统消息）
    for msg in conversation['messages']:
        if msg['role'] != 'system':
            # 处理文件消息
            if msg.get('is_file', False):
                chat_messages.append({
                    "role": "user",
                    "content": f"[文件消息] {msg['file_info']['display_id']}: {msg['file_info']['content_preview']}"
                })
            else:
                chat_messages.append({
                    "role": msg['role'],
                    "content": msg['content']
                })
    
    # 添加当前用户输入
    chat_messages.append({
        "role": "user",
        "content": user_input
    })
    
    # 更新会话标题
    if conversation['title'] == '新会话':
        # 从用户输入中提取合适的前30个字符作为标题
        conversation['title'] = user_input[:30] + ('...' if len(user_input) > 30 else '')
    
    # 调试日志
    logging.info(f"发送给AI的消息 (模型: {model}, Max Tokens: {max_tokens}):")
    for msg in chat_messages:
        logging.info(f"{msg['role'].upper()}: {msg['content'][:200]}{'...' if len(msg['content']) > 200 else ''}")
    
    try:
        # 创建流式响应
        response = client.chat.completions.create(
            model=model,  # 使用用户选择的模型
            messages=chat_messages,
            stream=True,
            temperature=0.7,
            max_tokens=max_tokens,  # 使用设置的最大长度
            timeout=30
        )
        
        # 流式传输函数 - 逐字输出
        def generate():
            assistant_response = ""
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    assistant_response += content
                    
                    # 逐字发送
                    for char in content:
                        # 添加轻微延迟以模拟打字机效果
                        time.sleep(0.005)
                        yield f"data: {json.dumps({'char': char})}\n\n"
            
            # 整个流式响应完成后，将完整的助手回复添加到消息历史中
            conversation['messages'].append({
                "role": "assistant", 
                "content": assistant_response,
                "is_file": False
            })
            # 发送结束事件
            yield "data: {\"done\": true}\n\n"
        
        return Response(generate(), mimetype='text/event-stream')
        
    except Exception as e:
        logging.error(f"聊天请求失败: {str(e)}")
        return jsonify({
            'error': f'⚠️ 发生错误: {str(e)}',
            'detail': '可能原因：API 密钥错误、网络问题或服务器不可用。'
        }), 500

@app.route('/conversations', methods=['GET'])
def get_conversations():
    """获取所有会话列表"""
    return jsonify({
        'status': 'success',
        'conversations': [
            {
                'id': conv['id'],
                'title': conv['title'],
                'createdAt': conv['createdAt'],
                'lastActive': conv.get('lastActive', conv['createdAt']),
                'starred': conv.get('starred', False),
                'file_count': len(conv.get('files', {}))
            }
            for conv in conversations.values()
        ]
    })

@app.route('/conversation/<session_id>', methods=['GET'])
def get_conversation_details(session_id):
    """获取特定会话详情"""
    conversation = get_conversation(session_id)
    
    # 构建响应
    response = {
        'id': conversation['id'],
        'title': conversation['title'],
        'createdAt': conversation['createdAt'],
        'lastActive': conversation.get('lastActive', conversation['createdAt']),
        'starred': conversation.get('starred', False),
        'settings': conversation.get('settings', DEFAULT_SETTINGS.copy()),
        'files': [
            {
                'file_id': file_info['file_id'],
                'filename': file_info['filename'],
                'type': file_info['type'],
                'display_id': file_info['display_id'],
                'short_id': file_info['short_id'],
                'upload_time': file_info['upload_time'],
                'preview_html': file_info['preview_html']
            }
            for file_info in conversation['files'].values()
        ],
        'messages': [
            {
                'role': msg['role'],
                'content': msg['content'],
                'is_file': msg.get('is_file', False),
                'timestamp': msg.get('timestamp', time.time())
            }
            for msg in conversation['messages']
            if msg['role'] != 'system'  # 排除系统消息
        ]
    }
    
    return jsonify(response)

@app.route('/conversation/<session_id>', methods=['DELETE'])
def delete_conversation(session_id):
    """删除会话"""
    if session_id in conversations:
        del conversations[session_id]
        return jsonify({'status': 'success', 'message': '会话已删除'})
    return jsonify({'status': 'error', 'message': '会话不存在'}), 404

@app.route('/star/<session_id>', methods=['POST'])
def star_conversation(session_id):
    """标记/取消标记会话为收藏"""
    if session_id in conversations:
        conversations[session_id]['starred'] = not conversations[session_id].get('starred', False)
        return jsonify({
            'status': 'success',
            'starred': conversations[session_id]['starred']
        })
    return jsonify({'status': 'error', 'message': '会话不存在'}), 404

@app.route('/file/<file_id>', methods=['GET'])
def get_file_content(file_id):
    """获取文件完整内容"""
    session_id = request.args.get('session_id', 'default')
    conversation = get_conversation(session_id)
    
    if file_id in conversation['files']:
        file_info = conversation['files'][file_id]
        return jsonify({
            'status': 'success',
            'filename': file_info['filename'],
            'content': file_info['content'],
            'display_id': file_info['display_id']
        })
    
    return jsonify({'status': 'error', 'message': '文件不存在'}), 404

def generate_file_preview_html(file_info):
    """生成文件预览的HTML代码"""
    filename_without_ext = os.path.splitext(file_info['filename'])[0]
    
    return f"""
    <div class="file-preview">
        <div class="file-info">
            <i class="fas {'fa-file-alt' if file_info['type'] == 'document' else 'fa-image'}"></i>
            {filename_without_ext} ({'文档' if file_info['type'] == 'document' else '图片'})
            <span class="file-context-tag">ID: <span class="file-id-highlight">{file_info['display_id']}</span></span>
        </div>
        <div class="preview-content">
            {file_info['content_preview']}
        </div>
        <div class="file-reference">
            在问题中使用 <span class="file-reference-tag">{file_info['display_id']}</span> 引用此文件
        </div>
    </div>
    """

def start_browser(port):
    """启动浏览器打开页面"""
    webbrowser.open(f'http://127.0.0.1:{port}')

if __name__ == '__main__':
    # 自动寻找可用端口
    port = find_free_port(5000, 5050)
    if port is None:
        port = 5000
        print("⚠️ 未找到可用端口，尝试使用5000端口")
    
    print(f"🚀🚀🚀🚀 服务器将在端口 {port} 启动")
    
    # 在独立线程中打开浏览器
    threading.Thread(target=start_browser, args=(port,)).start()
    
    # 启动Flask应用
    app.run(debug=False, port=port)