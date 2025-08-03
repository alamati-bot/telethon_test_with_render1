#!/usr/bin/env python3
"""
ملف تشغيل سريع لتطبيق محول رسائل Telegram
"""

import uvicorn
import os
from dotenv import load_dotenv

def main():
    """تشغيل التطبيق"""
    load_dotenv()
    
    # التحقق من وجود المتغيرات البيئية
    if not os.getenv('API_ID') or not os.getenv('API_HASH'):
        print("❌ خطأ: يجب إنشاء ملف .env يحتوي على API_ID و API_HASH")
        print("📝 مثال:")
        print("API_ID=12345678")
        print("API_HASH=your_api_hash_here")
        return
    
    if not os.getenv('PASSWORD'):
        print("❌ خطأ: يجب إنشاء ملف .env يحتوي على PASSWORD")
        print("📝 مثال:")
        print("PASSWORD=your_password_here")
        return
    
    if not os.getenv('SOURCE_CHANNEL'):
        print("❌ خطأ: يجب إنشاء ملف .env يحتوي على SOURCE_CHANNEL")
        print("📝 مثال:")
        print("SOURCE_CHANNEL=-1001234567890")
        return
    
    print("\033[92m✓\033[0m تم التحقق من وجود API_ID و API_HASH")
    print("\033[92m✓\033[0m تم التحقق من وجود PASSWORD")
    print("\033[92m✓\033[0m تم التحقق من وجود SOURCE_CHANNEL")
    print("\033[94mℹ\033[0m جاري بدء التطبيق...")
    print("\033[94mℹ\033[0m يمكنك الوصول إلى التطبيق من خلال: http://localhost:8000")
    print("\033[94mℹ\033[0m يجب إدخال كلمة المرور للوصول إلى النظام")
    print("\033[94mℹ\033[0m بعد إدخال كلمة المرور، سيتم محاولة الاتصال تلقائيًا بجلسة موجودة")
    print("\033[94mℹ\033[0m إذا لم يتم العثور على جلسة، سيتم إرسال كود تحقق تلقائيًا إلى الرقم +963980907351")
    print("\033[94mℹ\033[0m سيتم تحويل الرسائل فقط من القناة المحددة")
    print("\033[94mℹ\033[0m اضغط CTRL+C لإيقاف التطبيق")
    print("\033[93m⚠\033[0m لا تغلق هذه النافذة أثناء تشغيل التطبيق")
    print("-" * 50)
    
    # تشغيل التطبيق
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )

if __name__ == "__main__":
    main()
