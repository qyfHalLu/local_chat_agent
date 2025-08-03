
# app.py
import os
from dotenv import load_dotenv
from openai import OpenAI
from flask import Flask, render_template, request, jsonify, Response
import threading
import webbrowser
import json
import time

app = Flask(__name__)

load_dotenv(os.path.join(os.path.expanduser('~'), '.openai_env'))

# 配置OpenAI客户端
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://www.sophnet.com/api/open-apis/v1"
)

# 存储对话历史和状态
conversations = {}

def get_conversation(session_id):
    """获取或创建对话历史"""
    if session_id not in conversations:
        conversations[session_id] = [
            {"role": "system", "content": "你是伏秋杨的智能助手"}
        ]
    return conversations[session_id]

@app.route('/')
def home():
    """主页面路由"""
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    """处理聊天请求（逐字流式响应）"""
    data = request.json
    session_id = data.get('session_id', 'default')
    user_input = data['message'].strip()
    
    if not user_input:
        return jsonify({'error': '消息内容不能为空'}), 400
    
    # 获取对话历史
    messages = get_conversation(session_id)
    messages.append({"role": "user", "content": user_input})
    
    try:
        # 创建流式响应
        response = client.chat.completions.create(
            model="DeepSeek-V3-Fast",
            messages=messages,
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
                        time.sleep(0.02)
                        yield f"data: {json.dumps({'char': char})}\n\n"
            
            # 整个流式响应完成后，将完整的助手回复添加到消息历史中
            messages.append({"role": "assistant", "content": assistant_response})
            # 发送结束事件
            yield "data: {\"done\": true}\n\n"
        
        return Response(generate(), mimetype='text/event-stream')
        
    except Exception as e:
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
    app.run(debug=False)