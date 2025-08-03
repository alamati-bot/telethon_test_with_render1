from fastapi import FastAPI, Request, Form, HTTPException, Depends, Cookie, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from telethon import TelegramClient, events
from telethon.errors import PhoneCodeInvalidError
import os
import asyncio
import logging
from dotenv import load_dotenv
from typing import Dict, Optional, Union
import re

# إعداد logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# التحقق من وجود المتغيرات البيئية
api_id = os.getenv('API_ID')
api_hash = os.getenv('API_HASH')
password = os.getenv('PASSWORD')
source_channel = os.getenv('SOURCE_CHANNEL')

if not api_id or not api_hash:
    raise ValueError("يجب تعيين API_ID و API_HASH في ملف .env")

if not password:
    raise ValueError("يجب تعيين PASSWORD في ملف .env")

if not source_channel:
    raise ValueError("يجب تعيين SOURCE_CHANNEL في ملف .env")

api_id = int(api_id)
source_channel = int(source_channel)

app = FastAPI(title="Telegram Message Forwarder", version="1.0.0")
templates = Jinja2Templates(directory="templates")

# إعداد مجلد الجلسات
session_path = "session"
if not os.path.exists(session_path):
    os.makedirs(session_path)

# تخزين العملاء والجلسات النشطة
clients: Dict[str, TelegramClient] = {}
active_sessions: Dict[str, bool] = {}

def validate_phone(phone: str) -> bool:
    """التحقق من صحة رقم الهاتف"""
    # إزالة المسافات والرموز
    phone = re.sub(r'[\s\-\(\)]', '', phone)
    # التحقق من أن الرقم يبدأ بـ + ويحتوي على أرقام فقط
    return phone.startswith('+') and phone[1:].isdigit() and len(phone) >= 10

def validate_code(code: str) -> bool:
    """التحقق من صحة كود التحقق"""
    return code.isdigit() and len(code) >= 4

def verify_password(entered_password: str) -> bool:
    """التحقق من صحة كلمة المرور"""
    return entered_password == password

async def check_auth(auth_token: Optional[str] = Cookie(None)):
    """التحقق من تسجيل الدخول"""
    if auth_token != "authenticated":
        return False
    return True

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request, is_authenticated: bool = Depends(check_auth)):
    """صفحة تسجيل الدخول"""
    if is_authenticated:
        # التحقق من وجود جلسة نشطة
        phone = "+963980907351"  # الرقم المحدد
        has_active_session = False
        client_exists = False
        client_authorized = False
        error_message = None
        success_message = None
        
        # التحقق من وجود العميل في الذاكرة أولاً
        if phone in clients and clients[phone] is not None:
            client_exists = True
            try:
                client = clients[phone]
                # التحقق من حالة الاتصال
                if client.is_connected():
                    logger.info(f"العميل {phone} متصل")
                    # التحقق من حالة التفويض
                    if await client.is_user_authorized():
                        client_authorized = True
                        has_active_session = True
                        logger.info(f"العميل {phone} مفوض ولديه جلسة نشطة")
                        active_sessions[phone] = True
                    else:
                        logger.warning(f"العميل {phone} متصل ولكن غير مفوض")
                else:
                    logger.warning(f"العميل {phone} موجود ولكن غير متصل")
            except Exception as e:
                logger.error(f"خطأ في التحقق من حالة الجلسة: {e}")
                import traceback
                logger.error(traceback.format_exc())
        else:
            logger.info(f"لا يوجد عميل في الذاكرة للرقم {phone}، التحقق من ملف الجلسة")
            
            # التحقق من وجود ملف الجلسة
            session_name = f"{session_path}/{phone.replace('+', '')}"
            session_file = f"{session_name}.session"
            
            if os.path.exists(session_file):
                logger.info(f"تم العثور على ملف جلسة: {session_file}")
                
                # التحقق من حجم ملف الجلسة
                file_size = os.path.getsize(session_file)
                logger.info(f"حجم ملف الجلسة: {file_size} بايت")
                
                if file_size < 1:  # ملف صغير جداً قد يكون فارغاً أو تالفاً
                    logger.warning(f"ملف الجلسة صغير جداً ({file_size} بايت)، سيتم حذفه")
                    try:
                        os.remove(session_file)
                        logger.info(f"تم حذف ملف الجلسة الصغير: {session_file}")
                    except Exception as e:
                        logger.error(f"فشل في حذف ملف الجلسة: {e}")
                else:
                    # محاولة الاتصال بالجلسة
                    try:
                        logger.info(f"محاولة الاتصال بالجلسة للرقم {phone}")
                        client = TelegramClient(session_name, api_id, api_hash)
                        await client.connect()
                        
                        # التحقق من حالة الاتصال
                        if client.is_connected():
                            logger.info(f"تم الاتصال بالخادم بنجاح")
                            
                            # التحقق من التفويض
                            if await client.is_user_authorized():
                                logger.info(f"تم الاتصال بنجاح بالجلسة للرقم {phone}")
                                clients[phone] = client
                                active_sessions[phone] = True
                                has_active_session = True
                                client_exists = True
                                client_authorized = True
                                
                                # بدء عملية تحويل الرسائل
                                asyncio.create_task(start_message_forwarding(client, phone))
                            else:
                                logger.warning(f"الجلسة للرقم {phone} غير مصرح بها")
                                await client.disconnect()
                                # حذف الجلسة غير المصرح بها
                                try:
                                    os.remove(session_file)
                                    logger.info(f"تم حذف ملف الجلسة غير المصرح بها: {session_file}")
                                except Exception as e:
                                    logger.error(f"فشل في حذف ملف الجلسة: {e}")
                        else:
                            logger.error("فشل الاتصال بالخادم")
                            await client.disconnect()
                    except Exception as e:
                        logger.error(f"خطأ في الاتصال بالجلسة: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
            else:
                logger.info(f"لا توجد ملف جلسة للرقم {phone}")
        
        # تحديد الرسائل المناسبة بناءً على حالة الجلسة
        if has_active_session:
            success_message = "تم تسجيل الدخول تلقائيًا وتم الاتصال بجلسة نشطة\n سيتم تحويل جميع الرسائل تلقائياً\n يمكنك إغلاق هذه الصفحة"
            error_message = None
        elif client_exists and not client_authorized:
            success_message = "تم تسجيل الدخول بنجاح، ولكن الجلسة غير مفوضة"
            error_message = "يرجى إرسال كود التحقق لتفويض الجلسة"
        else:
            success_message = "تم تسجيل الدخول بنجاح"
            error_message = "لا توجد جلسة نشطة، يرجى إرسال كود التحقق لإنشاء جلسة جديدة"
        
        return templates.TemplateResponse("login.html", {
            "request": request,
            "show_password": False,
            "show_code": False,
            "error": error_message,
            "success": success_message,
            "is_authenticated": True,
            "has_active_session": has_active_session
        })
    else:
        return templates.TemplateResponse("login.html", {
            "request": request, 
            "show_password": True,
            "error": None,
            "success": None,
            "is_authenticated": False
        })

@app.get("/verify_code", response_class=HTMLResponse)
async def verify_code_page(request: Request, is_authenticated: bool = Depends(check_auth)):
    """صفحة التحقق من الكود المرسل تلقائيًا"""
    if not is_authenticated:
        return RedirectResponse(url="/", status_code=303)
    
    # التحقق من وجود جلسة نشطة
    phone = "+963980907351"  # الرقم المحدد
    has_active_session = False
    
    if phone in clients and clients[phone] is not None:
        try:
            client = clients[phone]
            if await client.is_user_authorized():
                has_active_session = True
                logger.info(f"المستخدم {phone} مسجل الدخول بالفعل، إعادة التوجيه إلى الصفحة الرئيسية")
                return RedirectResponse(url="/", status_code=303)
        except Exception as e:
            logger.error(f"خطأ في التحقق من حالة الجلسة: {e}")
    
    # التحقق من وجود عميل للرقم
    client_exists = phone in clients and clients[phone] is not None
    
    # التحقق من حالة التفويض إذا كان العميل موجوداً
    has_active_session = False
    if client_exists:
        try:
            client = clients[phone]
            if await client.is_user_authorized():
                has_active_session = True
        except Exception as e:
            logger.error(f"خطأ في التحقق من حالة التفويض: {e}")
    
    return templates.TemplateResponse("login.html", {
        "request": request,
        "show_password": False,
        "show_code": True,
        "phone": phone,
        "error": None if client_exists else "لم يتم إنشاء جلسة بعد، يرجى إرسال كود التحقق أولاً",
        "success": "تم إرسال كود التحقق إلى الرقم +963980907351" if client_exists else None,
        "is_authenticated": True,
        "has_active_session": has_active_session
    })

@app.post("/verify_code", response_class=HTMLResponse)
async def verify_code(request: Request, code: str = Form(...), is_authenticated: bool = Depends(check_auth)):
    """التحقق من كود التفعيل"""
    if not is_authenticated:
        return RedirectResponse(url="/", status_code=303)
    
    phone = "+963980907351"  # الرقم المحدد
    logger.info(f"محاولة التحقق من كود التفعيل للرقم {phone}")
        
    try:
        if phone not in clients or clients[phone] is None:
            # إذا لم يكن العميل موجودًا، حاول إنشاء عميل جديد وإرسال كود التحقق
            logger.warning(f"لا يوجد عميل للرقم {phone}، محاولة إنشاء عميل جديد وإرسال كود التحقق")
            try:
                # التحقق من وجود ملف جلسة قبل إرسال كود جديد
                session_name = f"{session_path}/{phone.replace('+', '')}" 
                session_file = f"{session_name}.session"
                
                if os.path.exists(session_file):
                    logger.info(f"تم العثور على ملف جلسة: {session_file}")
                    # التحقق من حجم الملف
                    file_size = os.path.getsize(session_file)
                    if file_size < 1:  # ملف صغير جداً قد يكون فارغاً أو تالفاً
                        logger.warning(f"ملف الجلسة صغير جداً ({file_size} بايت)، سيتم حذفه وإنشاء جلسة جديدة")
                        try:
                            os.remove(session_file)
                            logger.info(f"تم حذف ملف الجلسة الصغير: {session_file}")
                        except Exception as e:
                            logger.error(f"فشل في حذف ملف الجلسة: {e}")
                
                # إرسال كود جديد
                phone_result = await auto_send_code()
                if phone_result:
                    logger.info(f"تم إرسال كود تحقق جديد للرقم {phone_result}")
                    return templates.TemplateResponse("login.html", {
                        "request": request,
                        "error": None,
                        "success": "تم إرسال كود تحقق جديد، يرجى التحقق من هاتفك وإدخال الكود",
                        "show_code": True,
                        "phone": phone,
                        "is_authenticated": True,
                        "has_active_session": False
                    })
                else:
                    logger.error("فشل في إرسال كود التحقق تلقائيًا")
                    return templates.TemplateResponse("login.html", {
                        "request": request,
                        "error": "فشل في إرسال كود التحقق، يرجى المحاولة مرة أخرى",
                        "success": None,
                        "show_code": False,
                        "is_authenticated": True,
                        "has_active_session": False
                    })
            except Exception as e:
                logger.error(f"خطأ في إرسال كود التحقق تلقائيًا: {e}")
                import traceback
                logger.error(traceback.format_exc())
                
                # تحديد نوع الخطأ لعرض رسالة مناسبة للمستخدم
                error_message = f"حدث خطأ في إرسال كود التحقق: {str(e)}"
                if "flood" in str(e).lower():
                    error_message = "تم تجاوز الحد المسموح من المحاولات، يرجى الانتظار قبل المحاولة مرة أخرى"
                elif "network" in str(e).lower() or "connection" in str(e).lower():
                    error_message = "حدث خطأ في الاتصال بخادم Telegram، يرجى التحقق من اتصالك بالإنترنت والمحاولة مرة أخرى"
                
                return templates.TemplateResponse("login.html", {
                    "request": request,
                    "error": error_message,
                    "success": None,
                    "show_code": False,
                    "is_authenticated": True,
                    "has_active_session": False
                })

        client = clients[phone]
        
        # التحقق من حالة الاتصال
        if not client.is_connected():
            logger.warning(f"العميل {phone} غير متصل، محاولة إعادة الاتصال")
            await client.connect()
        
        # تسجيل الدخول باستخدام الكود
        logger.info(f"محاولة تسجيل الدخول باستخدام الكود للرقم {phone}")
        await client.sign_in(phone, code)
        
        # التحقق من نجاح تسجيل الدخول
        if await client.is_user_authorized():
            logger.info(f"تم تسجيل الدخول بنجاح للرقم {phone}")
            active_sessions[phone] = True
            
            # بدء عملية إعادة توجيه الرسائل
            asyncio.create_task(start_message_forwarding(client, phone))
            
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": None,
                "success": "تم تسجيل الدخول بنجاح وتم الاتصال بجلسة نشطة\n سيتم تحويل جميع الرسائل تلقائياً\n يمكنك إغلاق هذه الصفحة",
                "show_code": False,
                "is_authenticated": True,
                "has_active_session": True
            })
        else:
            logger.warning(f"فشل في تفويض العميل {phone} رغم عدم وجود أخطاء")
            return templates.TemplateResponse("login.html", {
                "request": request,
                "error": "فشل في تفويض الجلسة، يرجى المحاولة مرة أخرى",
                "success": None,
                "show_code": True,
                "phone": phone,
                "is_authenticated": True,
                "has_active_session": False
            })
    except PhoneCodeInvalidError:
        logger.error(f"كود التحقق غير صحيح للرقم {phone}")
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "كود التحقق غير صحيح، يرجى المحاولة مرة أخرى",
            "success": None,
            "show_code": True,
            "phone": phone,
            "is_authenticated": True,
            "has_active_session": False
        })
    except Exception as e:
        logger.error(f"خطأ في التحقق من الكود: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        # تحديد نوع الخطأ لعرض رسالة مناسبة للمستخدم
        error_message = f"حدث خطأ: {str(e)}"
        if "flood" in str(e).lower():
            error_message = "تم تجاوز الحد المسموح من المحاولات، يرجى الانتظار قبل المحاولة مرة أخرى"
        elif "expired" in str(e).lower():
            error_message = "انتهت صلاحية الكود، يرجى طلب كود جديد"
        elif "invalid" in str(e).lower():
            error_message = "الكود غير صحيح، يرجى التحقق والمحاولة مرة أخرى"
        
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": error_message,
            "success": None,
            "show_code": True,
            "phone": phone,
            "is_authenticated": True
        })

async def check_existing_sessions():
    """التحقق من وجود جلسات سابقة والاتصال بها"""
    try:
        # التحقق من وجود ملفات الجلسة
        if not os.path.exists(session_path):
            logger.info("لا توجد مجلدات جلسات")
            return None
            
        # البحث عن ملفات الجلسة
        session_files = [f for f in os.listdir(session_path) if f.endswith('.session')]
        logger.info(f"ملفات الجلسات الموجودة: {session_files}")
        
        if not session_files:
            logger.info("لا توجد ملفات جلسات")
            return None
            
        # محاولة الاتصال بالجلسة الأولى
        phone = "+963980907351"  # الرقم المحدد
        session_name = f"{session_path}/{phone.replace('+', '')}"
        session_file = f"{session_name}.session"
        
        logger.info(f"البحث عن ملف الجلسة: {session_file}")
        if os.path.exists(session_file):
            logger.info(f"تم العثور على جلسة للرقم {phone}")
            
            # التحقق من حجم ملف الجلسة
            file_size = os.path.getsize(session_file)
            logger.info(f"حجم ملف الجلسة: {file_size} بايت")
            
            if file_size < 1:  # ملف صغير جداً قد يكون فارغاً أو تالفاً
                logger.warning(f"ملف الجلسة صغير جداً ({file_size} بايت)، سيتم حذفه وطلب كود تحقق جديد")
                try:
                    os.remove(session_file)
                    logger.info(f"تم حذف ملف الجلسة الصغير: {session_file}")
                except Exception as e:
                    logger.error(f"فشل في حذف ملف الجلسة: {e}")
                return None
            
            # محاولة الاتصال بالجلسة
            try:
                client = TelegramClient(session_name, api_id, api_hash)
                await client.connect()
                
                # التحقق من حالة الاتصال
                is_connected = client.is_connected()
                logger.info(f"حالة الاتصال: {is_connected}")
                
                if not is_connected:
                    logger.error("فشل الاتصال بالخادم، سيتم حذف ملف الجلسة وطلب كود تحقق جديد")
                    try:
                        await client.disconnect()
                        os.remove(session_file)
                        logger.info(f"تم حذف ملف الجلسة بسبب فشل الاتصال: {session_file}")
                    except Exception as e:
                        logger.error(f"فشل في حذف ملف الجلسة: {e}")
                    return None
                
                # التحقق من التفويض
                is_authorized = await client.is_user_authorized()
                logger.info(f"حالة التفويض: {is_authorized}")
                
                if is_authorized:
                    logger.info(f"تم الاتصال بنجاح بالجلسة للرقم {phone}")
                    clients[phone] = client
                    active_sessions[phone] = True
                    asyncio.create_task(start_message_forwarding(client, phone))
                    return phone
                else:
                    logger.info(f"الجلسة للرقم {phone} غير مصرح بها، سيتم حذفها وطلب كود تحقق جديد")
                    await client.disconnect()
                    # حذف الجلسة غير المصرح بها إذا كانت موجودة
                    if os.path.exists(session_file):
                        try:
                            os.remove(session_file)
                            logger.info(f"تم حذف ملف الجلسة غير المصرح بها: {session_file}")
                        except Exception as e:
                            logger.error(f"فشل في حذف ملف الجلسة: {e}")
                    return None
            except Exception as e:
                logger.error(f"خطأ أثناء محاولة الاتصال بالجلسة: {e}")
                try:
                    os.remove(session_file)
                    logger.info(f"تم حذف ملف الجلسة بسبب خطأ في الاتصال: {session_file}")
                except Exception as e2:
                    logger.error(f"فشل في حذف ملف الجلسة: {e2}")
                return None
        else:
            logger.info(f"لا توجد جلسة للرقم {phone}")
            return None
    except Exception as e:
        logger.error(f"خطأ في التحقق من الجلسات: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

async def auto_send_code():
    """إرسال كود التحقق تلقائيًا للرقم المحدد"""
    try:
        phone = "+963980907351"  # الرقم المحدد
        session_name = f"{session_path}/{phone.replace('+', '')}"
        session_file = f"{session_name}.session"
        
        logger.info(f"محاولة إرسال كود التحقق للرقم: {phone}")
        
        # التحقق من وجود جلسة نشطة ومفوضة أولاً
        if phone in clients and phone in active_sessions and active_sessions[phone]:
            # التحقق من حالة الاتصال والتفويض
            try:
                client = clients[phone]
                if client.is_connected() and await client.is_user_authorized():
                    logger.info(f"يوجد جلسة نشطة ومفوضة للرقم {phone}، لا حاجة لإرسال كود جديد")
                    return phone
                else:
                    logger.warning(f"الجلسة الموجودة للرقم {phone} غير متصلة أو غير مفوضة، سيتم إنشاء جلسة جديدة")
                    # إغلاق الجلسة الحالية
                    await client.disconnect()
                    active_sessions[phone] = False
            except Exception as e:
                logger.error(f"خطأ في التحقق من حالة الجلسة الحالية: {e}")
                # إعادة تعيين حالة الجلسة
                active_sessions[phone] = False
        
        # التحقق من وجود جلسة سابقة
        if os.path.exists(session_file):
            logger.info(f"تم العثور على ملف جلسة سابق: {session_file}")
            # التحقق من حجم ملف الجلسة
            file_size = os.path.getsize(session_file)
            logger.info(f"حجم ملف الجلسة: {file_size} بايت")
            
            if file_size < 1:  # ملف صغير جداً قد يكون فارغاً أو تالفاً
                logger.warning(f"ملف الجلسة صغير جداً ({file_size} بايت)، سيتم حذفه وإنشاء جلسة جديدة")
                try:
                    os.remove(session_file)
                    logger.info(f"تم حذف ملف الجلسة الصغير: {session_file}")
                except Exception as e:
                    logger.error(f"فشل في حذف ملف الجلسة: {e}")
            else:
                # محاولة الاتصال بالجلسة الموجودة
                try:
                    client = TelegramClient(session_name, api_id, api_hash)
                    await client.connect()
                    
                    # التحقق من حالة الاتصال
                    is_connected = client.is_connected()
                    logger.info(f"حالة الاتصال بالجلسة الموجودة: {is_connected}")
                    
                    if is_connected:
                        # التحقق من حالة التفويض
                        is_authorized = await client.is_user_authorized()
                        logger.info(f"حالة التفويض للجلسة الموجودة: {is_authorized}")
                        
                        if is_authorized:
                            # الجلسة متصلة ومفوضة
                            logger.info(f"تم الاتصال بنجاح بالجلسة الموجودة للرقم {phone}")
                            clients[phone] = client
                            active_sessions[phone] = True
                            asyncio.create_task(start_message_forwarding(client, phone))
                            return phone
                except Exception as e:
                    logger.error(f"فشل في الاتصال بالجلسة الموجودة: {e}")
                    try:
                        # محاولة إغلاق الجلسة وحذف الملف
                        if 'client' in locals() and client is not None:
                            await client.disconnect()
                        if os.path.exists(session_file):
                            os.remove(session_file)
                            logger.info(f"تم حذف ملف الجلسة التالف: {session_file}")
                    except Exception as e2:
                        logger.error(f"فشل في تنظيف الجلسة التالفة: {e2}")
        
        # إنشاء عميل جديد وإرسال كود تحقق
        logger.info("إنشاء جلسة جديدة وإرسال كود تحقق")
        client = TelegramClient(session_name, api_id, api_hash)
        await client.connect()
        
        # التحقق من حالة الاتصال
        is_connected = client.is_connected()
        logger.info(f"حالة الاتصال بالجلسة الجديدة: {is_connected}")
        
        if not is_connected:
            logger.error("فشل الاتصال بخادم Telegram")
            return None
        
        # التحقق من حالة التفويض
        is_authorized = await client.is_user_authorized()
        logger.info(f"حالة التفويض للجلسة الجديدة: {is_authorized}")
        
        if not is_authorized:
            logger.info(f"إرسال كود التحقق تلقائيًا للهاتف: {phone}")
            try:
                await client.send_code_request(phone)
                clients[phone] = client
                active_sessions[phone] = False  # تعيين الجلسة كغير نشطة حتى يتم التحقق من الكود
                logger.info(f"تم إرسال كود التحقق بنجاح للرقم {phone}")
                return phone
            except Exception as e:
                logger.error(f"فشل في إرسال كود التحقق: {e}")
                await client.disconnect()
                return None
        else:
            # المستخدم مسجل الدخول بالفعل
            logger.info(f"المستخدم {phone} مسجل الدخول بالفعل")
            clients[phone] = client
            active_sessions[phone] = True
            asyncio.create_task(start_message_forwarding(client, phone))
            return phone
    except Exception as e:
        logger.error(f"خطأ في إرسال كود التحقق تلقائيًا: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None

@app.post("/login", response_class=HTMLResponse)
async def admin_login(request: Request, admin_password: str = Form(...)):
    """معالجة تسجيل دخول المسؤول"""
    if verify_password(admin_password):
        # تسجيل محاولة تسجيل الدخول
        logger.info("تم التحقق من كلمة المرور بنجاح، جاري التحقق من الجلسات الموجودة")
        
        # التحقق من وجود جلسات سابقة
        connected_phone = await check_existing_sessions()
        
        # تعيين ملف تعريف الارتباط للمصادقة
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key="auth_token", value="authenticated")
        
        if connected_phone:
            # تم الاتصال بجلسة موجودة
            logger.info(f"تم الاتصال بنجاح بجلسة موجودة للرقم {connected_phone}")
        else:
            # لم يتم العثور على جلسات صالحة
            logger.info("لم يتم العثور على جلسات صالحة، سيتم عرض خيار إرسال كود التحقق")
        
        return response
    else:
        logger.warning("محاولة تسجيل دخول فاشلة: كلمة المرور غير صحيحة")
        return templates.TemplateResponse("login.html", {
            "request": request,
            "show_password": True,
            "error": "كلمة المرور غير صحيحة",
            "success": None,
            "is_authenticated": False
        })

@app.post("/auto_send_code", response_class=HTMLResponse)
async def auto_send_code_handler(request: Request, is_authenticated: bool = Depends(check_auth)):
    """معالجة إرسال كود التحقق تلقائيًا"""
    if not is_authenticated:
        return RedirectResponse(url="/", status_code=303)
    
    logger.info("بدء عملية إرسال كود التحقق تلقائيًا")
    
    # التحقق من وجود جلسة نشطة ومفوضة أولاً
    phone = "+963980907351"  # الرقم المحدد
    
    # التحقق من وجود جلسة نشطة ومفوضة
    if phone in clients and clients[phone] is not None and phone in active_sessions and active_sessions[phone]:
        try:
            client = clients[phone]
            if await client.is_user_authorized():
                logger.info(f"المستخدم {phone} مسجل الدخول بالفعل ولديه جلسة نشطة، لا حاجة لإرسال كود تحقق")
                # المستخدم مسجل الدخول بالفعل، إعادة التوجيه إلى الصفحة الرئيسية
                return RedirectResponse(url="/", status_code=303)
        except Exception as e:
            logger.error(f"خطأ في التحقق من حالة الجلسة: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    # إرسال كود التحقق تلقائيًا
    try:
        logger.info("محاولة إرسال كود التحقق تلقائيًا")
        phone_result = await auto_send_code()
        
        if phone_result:
            # تم إرسال الكود بنجاح أو العثور على جلسة نشطة
            if phone in active_sessions and active_sessions[phone]:
                # تم العثور على جلسة نشطة ومفوضة
                logger.info(f"تم العثور على جلسة نشطة ومفوضة للرقم {phone_result}")
                return RedirectResponse(url="/", status_code=303)
            else:
                # تم إرسال كود تحقق جديد
                logger.info(f"تم إرسال كود التحقق بنجاح للرقم {phone_result}")
                return RedirectResponse(url="/verify_code", status_code=303)
        else:
            logger.error("فشل في إرسال كود التحقق تلقائيًا")
            # فشل في إرسال الكود تلقائيًا
            return templates.TemplateResponse("login.html", {
                "request": request,
                "show_password": False,
                "show_code": False,
                "error": "فشل في إرسال كود التحقق تلقائيًا، يرجى المحاولة مرة أخرى",
                "success": None,
                "is_authenticated": True,
                "has_active_session": False
            })
    except Exception as e:
        logger.error(f"استثناء أثناء إرسال كود التحقق: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        return templates.TemplateResponse("login.html", {
            "request": request,
            "show_password": False,
            "show_code": False,
            "error": f"حدث خطأ أثناء إرسال كود التحقق: {str(e)}",
            "success": None,
            "is_authenticated": True
        })

# تم إزالة وظيفة send_code لأننا نستخدم الآن auto_send_code
@app.post("/", response_class=HTMLResponse)
async def send_code(request: Request, phone: str = Form(...), code: str = Form(None), is_authenticated: bool = Depends(check_auth)):
    """معالجة تسجيل الدخول وإرسال كود التحقق - سيتم استبدالها بالاتصال التلقائي"""
    if not is_authenticated:
        return RedirectResponse(url="/", status_code=303)
    
    # تم تعطيل هذه الوظيفة لأننا نستخدم الآن auto_send_code
    return templates.TemplateResponse("login.html", {
        "request": request,
        "show_code": False,
        "error": "تم تعطيل هذه الوظيفة، يتم الآن استخدام الاتصال التلقائي",
        "success": None,
        "is_authenticated": True
    })

async def start_message_forwarding(client: TelegramClient, phone: str):
    """بدء عملية تحويل الرسائل"""
    try:
        logger.info(f"بدء تحويل الرسائل للمستخدم {phone}")
        
        # إعداد معالج الرسائل الجديدة
        @client.on(events.NewMessage(chats=source_channel))
        async def message_handler(event):
            try:
                # تجاهل الرسائل المرسلة من الحساب نفسه
                if event.is_private and event.sender_id == (await client.get_me()).id:
                    return
                
                # تحويل الرسالة إلى الحساب المحدد
                to_id = '@alamati_info'  # يمكن تغيير هذا حسب الحاجة
                
                # استخدام forward بدلاً من إرسال رسالة جديدة
                await client.forward_messages(to_id, event.message)
                
                logger.info(f"تم تحويل رسالة من {phone} من القناة {source_channel}")
                
            except Exception as e:
                logger.error(f"خطأ في تحويل الرسالة: {e}")

        # تشغيل العميل
        await client.run_until_disconnected()
        
    except Exception as e:
        logger.error(f"خطأ في عملية تحويل الرسائل للمستخدم {phone}: {e}")
    finally:
        active_sessions[phone] = False
        logger.info(f"انتهت عملية تحويل الرسائل للمستخدم {phone}")

@app.get("/status")
async def get_status():
    """عرض حالة الجلسات النشطة"""
    active_count = sum(active_sessions.values())
    total_clients = len(clients)
    
    return {
        "active_sessions": active_count,
        "total_clients": total_clients,
        "sessions": active_sessions
    }

@app.get("/logout/{phone}")
async def logout(phone: str):
    """تسجيل الخروج من حساب معين"""
    try:
        if phone in clients:
            client = clients[phone]
            await client.disconnect()
            del clients[phone]
            active_sessions[phone] = False
            return {"message": f"تم تسجيل الخروج من {phone}"}
        else:
            raise HTTPException(status_code=404, detail="الحساب غير موجود")
    except Exception as e:
        logger.error(f"خطأ في تسجيل الخروج: {e}")
        raise HTTPException(status_code=500, detail="خطأ في تسجيل الخروج")

@app.on_event("shutdown")
async def shutdown_event():
    """إغلاق جميع الجلسات عند إيقاف التطبيق"""
    logger.info("إغلاق جميع الجلسات...")
    for phone, client in clients.items():
        try:
            await client.disconnect()
        except Exception as e:
            logger.error(f"خطأ في إغلاق جلسة {phone}: {e}")
    clients.clear()
    active_sessions.clear()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

