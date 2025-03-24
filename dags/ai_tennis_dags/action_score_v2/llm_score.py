# 标准库导入
import os
from openai import OpenAI
import base64

from ai_tennis_dags.action_score_v2.vision_agent_fuction import process_tennis_video

from PIL import Image, ImageDraw, ImageFont
import numpy as np
import re
from airflow.models import Variable


def get_tennis_action_comment(action_image_path: str, model_name: str = "qwen-vl-max-latest", action_type: str = "击球准备动作") -> str:
    """
    通过阿里云的AI模型，获取网球动作的评论
    """
    system_prompt = f"专业的网球教练，擅长对网球动作进行分析和评价。请结合照片网球运动员的{action_type}的细节，给出评价。格式如下：\n" \
                    f"评分等级：S|A|B|C\n" \
                    f"动作评价：10字以内\n" \
                    f"动作建议：10字以内(如果比较完美，可以不给出建议)"

    #  base 64 编码格式
    def encode_image(image_path):
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    # 将xxxx/test.png替换为你本地图像的绝对路径
    base64_image = encode_image(action_image_path)
    client = OpenAI(
        # 若没有配置环境变量，请用百炼API Key将下行替换为：api_key="sk-xxx"
        api_key=Variable.get('DASHSCOPE_API_KEY'),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    # 获取动作评价  
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": [{"type":"text","text": system_prompt}]},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        # 需要注意，传入Base64，图像格式（即image/{format}）需要与支持的图片列表中的Content Type保持一致。"f"是字符串格式化的方法。
                        # PNG图像：  f"data:image/png;base64,{base64_image}"
                        # JPEG图像： f"data:image/jpeg;base64,{base64_image}"
                        # WEBP图像： f"data:image/webp;base64,{base64_image}"
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}, 
                    },
                ],
            }
        ],
    )
    return completion.choices[0].message.content

# 三张动作图片+得分合并到一张长图
def extract_score_from_comment(comment_text):
    """从评论文本中提取分数等级和具体评价"""
    score_level = re.search(r'评分等级：([SABC])', comment_text)
    score_level = score_level.group(1) if score_level else "C"
    
    # 根据等级设置分数
    score_map = {"S": 95, "A": 85, "B": 75, "C": 60}
    score = score_map.get(score_level, 60)
    
    # 提取各项评价
    evaluations = []
    for line in comment_text.split('\n'):
        if "：" in line and "评分等级" not in line:
            key, value = line.split("：", 1)
            evaluations.append((key, value))
    
    return score, evaluations

def create_score_image(width, height, score, color):
    """创建一个带有分数的圆形图像"""
    img = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    
    # 画圆
    draw.ellipse((0, 0, width, height), fill=color)
    
    # 添加分数文字
    font_size = height // 2
    try:
        font = ImageFont.truetype("SimHei", font_size)
    except IOError:
        font = ImageFont.load_default()
    
    text = f"{score}分"
    text_width, text_height = draw.textbbox((0, 0), text, font=font)[2:]
    position = ((width - text_width) // 2, (height - text_height) // 2)
    draw.text(position, text, fill="white", font=font)
    
    return img

def merge_images_with_scores(preparation_image, preparation_score, 
                            contact_image, contact_score,
                            follow_image, follow_score,
                            output_path="/tmp/tennis_analysis.jpg"):
    """合并三张图片和评分为一张长图"""
    # 打开三张图片
    prep_img = Image.open(preparation_image)
    contact_img = Image.open(contact_image)
    follow_img = Image.open(follow_image)
    
    # 调整所有图片为相同宽度
    width = 800
    height = int(width * prep_img.height / prep_img.width)
    
    prep_img = prep_img.resize((width, height))
    contact_img = contact_img.resize((width, height))
    follow_img = follow_img.resize((width, height))
    
    # 解析评分
    prep_score, prep_eval = extract_score_from_comment(preparation_score)
    contact_score, contact_eval = extract_score_from_comment(contact_score)
    follow_score, follow_eval = extract_score_from_comment(follow_score)
    
    # 设置颜色 (分数<70用橙色，否则用绿色)
    prep_color = (255, 128, 0) if prep_score < 70 else (0, 150, 0)
    contact_color = (255, 128, 0) if contact_score < 70 else (0, 150, 0)
    follow_color = (255, 128, 0) if follow_score < 70 else (0, 150, 0)
    
    # 创建分数图标
    score_size = 150
    prep_score_img = create_score_image(score_size, score_size, prep_score, prep_color)
    contact_score_img = create_score_image(score_size, score_size, contact_score, contact_color)
    follow_score_img = create_score_image(score_size, score_size, follow_score, follow_color)
    
    # 设置每个部分的标题
    titles = ["【引拍准备】", "【发力启动】", "【挥拍击球】"]
    
    # 设置每个部分的高度（图片+评分+评价）
    section_height = height + 200  # 图片高度 + 评分和评价的额外空间
    
    # 创建最终图像
    final_height = section_height * 3
    final_image = Image.new("RGB", (width, final_height), (255, 255, 255))
    
    # 设置字体
    try:
        # 尝试加载中文字体，支持多种系统环境
        font_paths = [
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",  # Linux
            "/System/Library/Fonts/PingFang.ttc",  # macOS
            "C:/Windows/Fonts/simhei.ttf",  # Windows
            "SimHei"  # 尝试直接按名称加载
        ]
        
        title_font = None
        for font_path in font_paths:
            try:
                title_font = ImageFont.truetype(font_path, 40)
                eval_font = ImageFont.truetype(font_path, 30)
                break
            except IOError:
                continue
                
        if title_font is None:
            title_font = ImageFont.load_default()
            eval_font = ImageFont.load_default()
    except Exception:
        title_font = ImageFont.load_default()
        eval_font = ImageFont.load_default()
    
    draw = ImageDraw.Draw(final_image)
    
    # 绘制第一部分：准备动作
    y_offset = 0
    # 标题
    draw.text((20, y_offset), titles[0], fill=(0, 0, 0), font=title_font)
    # 图片
    final_image.paste(prep_img, (0, y_offset + 50))
    # 分数
    final_image.paste(prep_score_img, (20, y_offset + height + 60), prep_score_img)
    # 评价
    eval_y = y_offset + height + 60
    for item, value in prep_eval:
        draw.text((200, eval_y), f"【{item}】 {value}", fill=(0, 0, 0), font=eval_font)
        eval_y += 40
    
    # 绘制第二部分：发力启动
    y_offset = section_height
    # 标题
    draw.text((20, y_offset), titles[1], fill=(0, 0, 0), font=title_font)
    # 图片
    final_image.paste(contact_img, (0, y_offset + 50))
    # 分数
    final_image.paste(contact_score_img, (20, y_offset + height + 60), contact_score_img)
    # 评价
    eval_y = y_offset + height + 60
    for item, value in contact_eval:
        draw.text((200, eval_y), f"【{item}】 {value}", fill=(0, 0, 0), font=eval_font)
        eval_y += 40
    
    # 绘制第三部分：跟随动作
    y_offset = section_height * 2
    # 标题
    draw.text((20, y_offset), titles[2], fill=(0, 0, 0), font=title_font)
    # 图片
    final_image.paste(follow_img, (0, y_offset + 50))
    # 分数
    final_image.paste(follow_score_img, (20, y_offset + height + 60), follow_score_img)
    # 评价
    eval_y = y_offset + height + 60
    for item, value in follow_eval:
        draw.text((200, eval_y), f"【{item}】 {value}", fill=(0, 0, 0), font=eval_font)
        eval_y += 40
    
    # 保存最终图像
    final_image.save(output_path)
    
    return output_path


def get_tennis_action_score(video_path: str, output_dir: str):
    """
    获取网球动作得分
    """
    result = process_tennis_video(video_path, output_dir)
    print(f"result: {result}")

    preparation_image = result["preparation_frame"]
    contact_image = result["contact_frame"]
    follow_image = result["follow_frame"]

    # 获取准备动作得分
    preparation_score = get_tennis_action_comment(preparation_image, action_type="准备动作")
    print(f"preparation_score: {preparation_score}")

    # 获取击球动作得分
    contact_score = get_tennis_action_comment(contact_image, action_type="击球动作")
    print(f"contact_score: {contact_score}")

    # 获取跟随动作得分
    follow_score = get_tennis_action_comment(follow_image, action_type="跟随动作")
    print(f"follow_score: {follow_score}")
    
    # 合并三张图片和评分
    output_image = merge_images_with_scores(
        preparation_image, preparation_score,
        contact_image, contact_score,
        follow_image, follow_score,
        output_path=f"{output_dir}/tennis_analysis_{os.path.basename(video_path).split('.')[0]}.jpg"
    )
    
    # 将合并后的图片路径添加到结果中
    result["analysis_image"] = output_image

    print(f"result: {result}")
    return result
