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

def get_conversation(session_id):
    """获取或创建对话历史"""
    if session_id not in conversations:
        conversations[session_id] = {
            "id": session_id,
            "title": "新会话",
            "messages": [
                {"role": "system", "content": "你是伏秋杨的智能助手，负责分析用户提供的文件和图片内容。"}
            ],
            "files": {},
            "createdAt": time.time(),
            "starred": False
        }
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

@app.route('/')
def home():
    """主页面路由"""
    return render_template('index.html')

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

# 文件上传路由
@app.route('/upload', methods=['POST'])
def handle_upload():
    session_id = request.form.get('session_id', 'default')
    file_type = request.form.get('type')
    
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': '未选择文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': '未选择文件'}), 400
    
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
        
        # 添加文件到对话上下文
        file_info = {
            "type": file_type,
            "filename": original_filename,
            "content": result.get('content', result.get('text', '')),
            "file_id": file_id,
            "short_id": short_id,
            "display_id": f"文件{short_id}",
            "upload_time": time.time()
        }
        
        conversation['files'][file_id] = file_info
        
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
            'content': file_info['content'],
            'file_id': file_id,
            'short_id': short_id,
            'display_id': file_info['display_id']
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

@app.route('/chat', methods=['POST'])
def chat():
    """处理聊天请求（逐字流式响应）"""
    data = request.json
    session_id = data.get('session_id', 'default')
    user_input = data['message'].strip()
    
    if not user_input:
        return jsonify({'error': '消息内容不能为空'}), 400
    
    # 获取对话上下文
    conversation = get_conversation(session_id)
    
    # 准备聊天消息
    chat_messages = []
    
    # 添加系统提示
    chat_messages.append({
        "role": "system",
        "content": "你是伏秋杨的智能助手，负责分析用户提供的文件和图片内容。"
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
                    "content": f"[文件消息] {msg['file_info']['display_id']}: {msg['file_info']['content'][:200]}..."
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
    
    # 调试日志
    logging.info("发送给AI的消息:")
    for msg in chat_messages:
        logging.info(f"{msg['role'].upper()}: {msg['content'][:200]}{'...' if len(msg['content']) > 200 else ''}")
    
    try:
        # 创建流式响应
        response = client.chat.completions.create(
            model="DeepSeek-V3-Fast",
            messages=chat_messages,
            stream=True,
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
                        time.sleep(0.01)
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

def start_browser():
    """启动浏览器打开页面"""
    webbrowser.open('http://127.0.0.1:5000')

if __name__ == '__main__':
    # 在独立线程中打开浏览器
    threading.Thread(target=start_browser).start()
    # 启动Flask应用
    app.run(debug=False, port=5000)