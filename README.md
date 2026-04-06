# Sahar v0.1.14

Sahar یک سیستم مدیریت **Xray / VLESS** با محوریت **Telegram** است.
این پروژه به شما کمک می‌کند یک سرور Master برای مدیریت داشته باشید و در صورت نیاز چند Agent روی سرورهای دیگر اضافه کنید تا ساخت کاربر، مدیریت سرورها، subscription، DNS و عملیات نگه‌داری را از یک جا کنترل کنید.

این پروژه را با عشق و احترام، به یاد **سحر عزیزم** تقدیم می‌کنم؛
کسی که برای آرمان آزادی، جانِ گران‌قدرش را فدا کرد و یادش همیشه زنده خواهد ماند.

---

## Sahar دقیقاً چه کاری انجام می‌دهد؟

Sahar این کارها را انجام می‌دهد:

- نصب و مدیریت یک **Master Server** برای کنترل کل سیستم
- نصب و مدیریت یک یا چند **Agent Server** برای اجرای Xray روی نودهای VPN
- ساخت و حذف کاربرها از داخل Telegram
- ساخت **subscription ثابت** برای هر کاربر
- مدیریت دسترسی هر کاربر به:
  - یک سرور
  - چند سرور
  - یا همه سرورها
- پشتیبانی از دو پروفایل روی هر سرور:
  - `VLESS | Simple`
  - `VLESS | Reality`
- اتصال به **Cloudflare** برای ساخت خودکار DNS رکورد هر نود
- ثبت خطاها، لاگ‌ها، وضعیت سرورها و گزارش‌های سیستم

به زبان ساده:
**Master** مغز سیستم است و **Agent** روی هر سرور VPN کارهای مربوط به Xray را انجام می‌دهد.

---

## معماری پروژه

### 1) Master
Master این بخش‌ها را اجرا می‌کند:

- Telegram Bot
- SQLite Database
- Subscription Service
- Scheduler
- Backup Manager
- Cloudflare Manager
- Provisioner برای اضافه‌کردن Agent با SSH

Master می‌تواند:
- فقط نقش مدیریتی داشته باشد
- یا خودش هم به عنوان **Local Node** استفاده شود

### 2) Agent
Agent روی هر VPS اجرا می‌شود و این کارها را انجام می‌دهد:

- نصب و اجرای Xray
- ساخت و حذف کاربر در Xray
- فعال/غیرفعال کردن کاربر
- ریستارت Xray
- برگرداندن آمار مصرف
- برگرداندن سلامت نود

---

## ساختار فایل‌ها

```text
install_master.sh
install_agent.sh
master_app/
  agent_client.py
  backup_manager.py
  bootstrap_cloudflare.py
  bot.py
  cloudflare_manager.py
  db.py
  error_tools.py
  notifier.py
  provisioner.py
  register_local_server.py
  requirements.txt
  scheduler.py
  subscription_api.py
  utils.py
agent_app/
  agent_api.py
  requirements.txt
  utils.py
  xray_manager.py
VERSION
LICENSE
README.md
```

---

## پیش‌نیازها

### سیستم‌عامل پیشنهادی
- Ubuntu 22.04 / 24.04
- Debian 12+

### حداقل سخت‌افزار پیشنهادی

#### Master فقط مدیریتی
- 1 vCPU
- 1 GB RAM
- 10 GB SSD

#### Master + Local Node
- 2 vCPU
- 2 GB RAM
- 20 GB SSD

#### هر Agent
- 1 vCPU
- 1 GB RAM
- 10 GB SSD

### نیازهای عمومی
- دسترسی root یا sudo
- اینترنت روی سرور
- دسترسی Telegram برای بات
- اگر Cloudflare می‌خواهی:
  - دامنه داخل Cloudflare
  - API Token با دسترسی حداقل لازم

---

## نصب Master

روی سرور Master فایل را اجرا کن:

```bash
sudo bash install_master.sh
```

در نصب، از تو این موارد پرسیده می‌شود:

- Telegram Bot Token
- Admin Chat IDs
- تنظیمات scheduler
- اگر خواستی، فعال‌سازی **Local Node**
- در صورت فعال بودن Local Node:
  - نوع public host
  - domain یا IP
  - پورت‌ها
  - تنظیمات Reality و Simple
- اگر Cloudflare را فعال کنی:
  - Domain name
  - Base subdomain (اختیاری)
  - API token

### خروجی Master
پس از نصب Master معمولاً این سرویس‌ها بالا می‌آیند:

- `sahar-master-bot`
- `sahar-master-scheduler`
- `sahar-master-subscription`
- و اگر Local Node فعال باشد:
  - `sahar-master-local-agent`
  - `xray`

---

## نصب Agent

روی هر VPS که می‌خواهی نود VPN باشد:

```bash
sudo bash install_agent.sh
```

در نصب Agent، این چیزها پرسیده می‌شوند:

- public IP یا domain
- نوع پروفایل‌ها و پورت‌ها
- تنظیمات Reality
- تنظیمات Agent API

### خروجی Agent
پس از نصب Agent معمولاً این سرویس‌ها بالا می‌آیند:

- `sahar-agent`
- `xray`

---

## Master + Local Node یعنی چه؟

اگر هنگام نصب Master گزینه Local Node را فعال کنی:

- همان سرور هم Master می‌شود
- هم Xray روی آن نصب می‌شود
- هم Local Agent بالا می‌آید

این حالت برای شروع خیلی مناسب است، چون لازم نیست یک VPS جدا فقط برای مدیریت داشته باشی.

---

## مدل کاربر در Sahar

### Subscription ثابت
برای هر کاربر یک **subscription link ثابت** ساخته می‌شود.
این لینک با اضافه یا حذف شدن سرورها تغییر نمی‌کند.

### دسترسی به سرورها
برای هر کاربر می‌توان تعیین کرد:
- فقط به یک سرور
- به چند سرور
- یا به همه سرورها
دسترسی داشته باشد

### پروفایل‌های اتصال
روی هر سرور دو نوع پروفایل ساخته می‌شود:
- `VLESS | Simple`
- `VLESS | Reality`

اگر کاربر به چند سرور دسترسی داشته باشد، در subscription او برای هر سرور مجاز، هر دو پروفایل دیده می‌شود.

---

## Cloudflare integration

اگر Cloudflare را در Master فعال کنی:

- token به‌صورت رمز‌شده نگه‌داری می‌شود
- برای هر سرور جدید می‌توان DNS record ساخت
- اگر Base subdomain بدهی، نام‌ها به این شکل ساخته می‌شوند:

مثال:
- domain: `example.com`
- base subdomain: `vpn`
- server name: `ir1`

خروجی:
- `ir1.vpn.example.com`

اگر Base subdomain خالی باشد:
- `ir1.example.com`

### نکته مهم
برای استفاده معمولی VLESS، رکوردها بهتر است **DNS-only** باشند، نه proxied.

---

## اضافه‌کردن سرور جدید با SSH

Sahar می‌تواند از داخل Telegram یا منطق Master، یک Agent را به‌صورت خودکار روی VPS جدید نصب کند.

اطلاعات لازم:
- host یا IP
- SSH port
- SSH username
- SSH password

جریان کلی:
1. اتصال با SSH
2. انتقال فایل‌های Agent
3. اجرای `install_agent.sh`
4. health check
5. ثبت سرور در Master
6. اگر Cloudflare فعال باشد، ساخت یا به‌روزرسانی رکورد DNS

---

## مدیریت از داخل Telegram

Bot تلگرام برای مدیریت سیستم استفاده می‌شود.
بسته به نسخه و تنظیمات، بخشی از عملیات دکمه‌ای و بخشی دستوری هستند.

کارهایی که ادمین می‌تواند انجام دهد:
- ساخت کاربر
- حذف کاربر
- فعال/غیرفعال کردن کاربر
- تنظیم حجم و زمان
- مدیریت دسترسی کاربر به سرورها
- ساخت subscription link
- گرفتن QR
- اضافه‌کردن سرور
- حذف سرور
- بررسی health report
- مشاهده آخرین خطاها
- مشاهده وضعیت Xray

### نقش‌های ادمین
- `owner`
- `admin`
- `support`
- `viewer`

---

## گزارش و نگه‌داری

Sahar این بخش‌ها را برای نگه‌داری دارد:

- Scheduler برای sync مصرف و هشدارها
- Backup Manager
- Error Reporting
- Audit Logs
- Provisioning State برای سرورها

### نمونه کارهای Scheduler
- sync مصرف کاربر از سرورهای مجاز
- disable کاربران منقضی
- disable کاربران over-quota
- هشدار نزدیک انقضا
- هشدار نزدیک اتمام حجم

---

## لاگ‌ها و عیب‌یابی

### وضعیت سرویس‌ها

```bash
systemctl status sahar-master-bot
systemctl status sahar-master-scheduler
systemctl status sahar-master-subscription
systemctl status sahar-master-local-agent
systemctl status sahar-agent
systemctl status xray
```

### لاگ‌ها

```bash
journalctl -u sahar-master-bot -f
journalctl -u sahar-master-scheduler -f
journalctl -u sahar-master-subscription -f
journalctl -u sahar-master-local-agent -f
journalctl -u sahar-agent -f
journalctl -u xray -f
```

### تست Xray

```bash
xray version
xray run -test -config /usr/local/etc/xray/config.json
```

### چک پورت‌ها

```bash
ss -tulpn | grep -E '443|8787|10085'
```

---

## نکات مهم امنیتی

- بهتر است Cloudflare Token فقط دسترسی لازم داشته باشد
- بهتر است روی Agent دسترسی‌ها محدود شوند
- بهتر است SSH provisioning فقط برای bootstrap استفاده شود
- بهتر است پسوردهای SSH در جای دیگری ذخیره نشوند
- backupها می‌توانند شامل اطلاعات حساس باشند؛ آن‌ها را امن نگه‌داری کن

---



## دانلود از GitHub و نصب سریع

اگر پروژه را روی GitHub با نام `Sahar` داخل حساب `PooyanGhorbani` گذاشتی، دوستانت می‌توانند مستقیم این‌طور دانلود و نصب کنند:

### دانلود از GitHub
```bash
git clone https://github.com/PooyanGhorbani/Sahar.git
cd Sahar
chmod +x install_master.sh install_agent.sh
```

### نصب Master
```bash
sudo ./install_master.sh
```

### نصب Agent
روی هر سرور Agent:
```bash
sudo ./install_agent.sh
```

### اگر Git نداشتند
```bash
wget https://github.com/PooyanGhorbani/Sahar/archive/refs/heads/main.zip -O sahar.zip
unzip sahar.zip
cd Sahar-main
chmod +x install_master.sh install_agent.sh
sudo ./install_master.sh
```

> اگر نام ریپوی GitHub را چیزی غیر از `Sahar` گذاشتی، فقط آدرس بالا را با نام ریپوی واقعی خودت عوض کن.

---
## اجرای سریع

### حالت ساده و پیشنهادی برای شروع
1. یک VPS بگیر
2. `install_master.sh` را اجرا کن
3. Local Node را فعال کن
4. Bot را در Telegram تست کن
5. اگر لازم شد، بعداً Agentهای بیشتر اضافه کن

### حالت چندسروری
1. روی VPS اصلی `install_master.sh`
2. روی VPSهای دیگر `install_agent.sh`
3. Agentها را در Master ثبت کن
4. برای کاربران access تعیین کن

---

## نسخه فعلی

نسخه داخل این بسته:

```text
0.1.14
```

---

## لایسنس

این پروژه با فایل `LICENSE` داخل همین بسته منتشر شده است.
