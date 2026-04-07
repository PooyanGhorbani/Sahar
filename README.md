# سحر 0.1.17

![Sahar banner](assets/banner.png)

**سامانه مدیریت Xray / VLESS با پنل تلگرام، مستر و ایجنت**  
**Telegram-first Xray / VLESS management platform with master-agent architecture**

![version](https://img.shields.io/badge/version-0.1.17-8b5cf6)
![platform](https://img.shields.io/badge/linux-Debian%20%7C%20Ubuntu%20%7C%20Alpine-0ea5e9)
![profiles](https://img.shields.io/badge/VLESS-Reality%20%2B%20Simple-22c55e)
![panel](https://img.shields.io/badge/Panel-Telegram-2563eb)

> **نکته مهم:** این بسته فقط برای **Ubuntu / Debian / Alpine** آماده شده و نصب آن باید با **دسترسی root** انجام شود.
>
> **Important:** This bundle supports **Ubuntu / Debian / Alpine** only and must be installed with **root** privileges.

---

## معرفی کوتاه | Overview

**سحر** برای این ساخته شده که مدیریت Xray را از حالت دستی و پراکنده خارج کند و آن را به یک جریان متمرکز تبدیل کند:

- **Master** برای مدیریت مرکزی
- **Agent** برای اجرای عملیات روی هر سرور
- **Telegram Bot** برای مدیریت روزانه
- **Subscription ثابت** برای هر کاربر
- **Cloudflare DNS Automation** به‌صورت اختیاری
- **SSH Provisioning** برای نصب Agent از داخل بات

در عمل، Master دیتابیس، بات، سرویس subscription و زمان‌بند را اجرا می‌کند و Agent روی هر نود، تغییرات Xray و وضعیت سرویس را مدیریت می‌کند.

---

## چیزی که این بسته واقعاً شاملش هست | What is included

این فایل ZIP شامل این موارد است:

- `install.sh` برای شروع نصب
- `install_master.sh` برای نصب Master
- `install_agent.sh` برای نصب Agent
- `master_app/` کدهای Master
- `agent_app/` کدهای Agent
- `assets/` تصاویر README
- `VERSION` نسخه بسته
- `PATCH_NOTES.txt` توضیحات تغییرات

**روش درست استفاده از این بسته:**

```bash
unzip sahar_0.1.17_single_installer_readme_fixed.zip
cd sahar_0.1.17_single_installer
sudo sh install.sh
```

اگر حالت نصب را در همان ابتدا مشخص کنی:

```bash
sudo sh install.sh master
```

یا:

```bash
sudo sh install.sh agent
```

اگر آرگومان ندهی، installer از خودت می‌پرسد که می‌خواهی **Master** نصب شود یا **Agent**.

---

## سیستم‌عامل‌های پشتیبانی‌شده | Supported operating systems

این installer خانواده سیستم‌عامل را به‌صورت خودکار تشخیص می‌دهد:

- **Ubuntu / Debian**
- **Alpine**

پشت صحنه هم از ابزار مناسب همان سیستم استفاده می‌کند:

- روی **Debian/Ubuntu** از `apt` و `systemd`
- روی **Alpine** از `apk` و `OpenRC`

یعنی لازم نیست خودت بین systemd و OpenRC چیزی را دستی تغییر بدهی.

---

## معماری پروژه | Architecture

### 1) Master
Master این بخش‌ها را اجرا می‌کند:

- Telegram Bot
- SQLite Database
- Subscription HTTP Service
- Scheduler
- Backup Manager
- Cloudflare bootstrap/manager
- SSH Provisioner

Master می‌تواند فقط نقش مدیریتی داشته باشد، یا در زمان نصب به‌صورت اختیاری **Local Node** هم روی همان سرور فعال شود.

### 2) Agent
Agent روی هر VPS اجرا می‌شود و این کارها را انجام می‌دهد:

- مدیریت کاربران Xray
- فعال/غیرفعال کردن کاربر
- حذف و اضافه کاربر
- بازخوانی و ری‌استارت سرویس Xray
- دریافت آمار مصرف از Xray API
- گزارش سلامت نود به Master

### 3) پنل تلگرام | Telegram panel
بات تلگرام برای عملیات روزمره استفاده می‌شود؛ مثل ساخت کاربر، تغییر پلن، مشاهده لینک، ساخت QR، افزودن سرور و بررسی سلامت.

---

## پروفایل‌ها و خروجی کاربر | User profiles and output

برای هر کاربر یک **subscription ثابت** ساخته می‌شود. این یعنی:

- لینک subscription کاربر ثابت می‌ماند
- با اضافه یا حذف شدن سرورها، خود لینک عوض نمی‌شود
- محتوای subscription به‌روزرسانی می‌شود

پروفایل‌هایی که پروژه برای نودها می‌سازد:

- `VLESS | Reality`
- `VLESS | Simple`

در نسخه فعلی، subscription هر دو پروفایل را در اختیار کلاینت قرار می‌دهد.

---

## نصب سریع | Quick start

### حالت 1: فقط یک VPS داری
اگر فقط یک سرور داری، معمولاً بهترین حالت این است که **Master** را نصب کنی و در زمان نصب، **Local Node** را هم فعال کنی.

```bash
unzip sahar_0.1.17_single_installer_readme_fixed.zip
cd sahar_0.1.17_single_installer
sudo sh install.sh master
```

در جریان نصب، وقتی این سؤال را دیدی:

```text
Enable local VPN node on this master server? [Y/n]
```

اگر پاسخ `Y` بدهی، همان سرور هم Master می‌شود و هم یک نود محلی خواهد داشت.

### حالت 2: چند VPS داری
روی سرور اصلی:

```bash
sudo sh install.sh master
```

روی هر سرور اضافه:

```bash
sudo sh install.sh agent
```

---

## در نصب Master چه چیزهایی از شما پرسیده می‌شود؟ | Master installer prompts

اسکریپت `install_master.sh` به‌صورت تعاملی این موارد را می‌پرسد:

- `Telegram bot token`
- `Admin chat IDs`
- فاصله اجرای scheduler
- timeout ارتباط با Agent
- حد آستانه هشدار زمان و مصرف
- تنظیمات backup
- آدرس عمومی subscription مثل:
  - `https://sub.example.com`
  - یا `http://IP:8090`
- تنظیمات bind سرویس subscription
- فعال/غیرفعال بودن Cloudflare
- در صورت فعال بودن Cloudflare:
  - دامنه
  - base subdomain
  - API token
- فعال/غیرفعال بودن Local Node
- اگر Local Node فعال باشد:
  - نام سرور
  - IP یا دامنه عمومی
  - تنظیمات Reality
  - پورت‌های Simple / Reality / Xray API / Local Agent

**پورت پیش‌فرض subscription روی Master:** `8090`

---

## در نصب Agent چه چیزهایی از شما پرسیده می‌شود؟ | Agent installer prompts

اسکریپت `install_agent.sh` این موارد را می‌پرسد:

- نام نمایشی Agent
- IP یا دامنه عمومی نود
- تنظیمات `Reality serverName/SNI`
- تنظیمات `Reality dest`
- fingerprint
- پورت `VLESS Simple`
- پورت `VLESS Reality`
- پورت `Xray API stats`
- آدرس bind و پورت API ایجنت
- `Allowed source IPs/CIDRs`
- `Agent API token`

**پورت پیش‌فرض Agent API:** `8787`  
**پورت پیش‌فرض Simple:** `443`  
**پورت پیش‌فرض Reality:** `8443`  
**پورت پیش‌فرض Xray API stats:** `10085`

---

## وضعیت سرویس‌ها بعد از نصب | Services after installation

### روی Master
در Debian/Ubuntu:

```bash
systemctl status sahar-master-bot
systemctl status sahar-master-scheduler
systemctl status sahar-master-subscription
```

اگر Local Node را فعال کرده باشی:

```bash
systemctl status sahar-master-local-agent
systemctl status xray
```

در Alpine:

```bash
rc-service sahar-master-bot status
rc-service sahar-master-scheduler status
rc-service sahar-master-subscription status
```

اگر Local Node فعال باشد:

```bash
rc-service sahar-master-local-agent status
rc-service xray status
```

### روی Agent
در Debian/Ubuntu:

```bash
systemctl status sahar-agent
systemctl status xray
```

در Alpine:

```bash
rc-service sahar-agent status
rc-service xray status
```

---

## مسیرهای مهم | Important paths

### Master
- مسیر اصلی برنامه: `/opt/sahar-master`
- فایل کانفیگ: `/opt/sahar-master/data/config.json`
- لاگ‌ها: `/opt/sahar-master/logs/`

### Agent
- مسیر اصلی برنامه: `/opt/sahar-agent`
- فایل کانفیگ: `/opt/sahar-agent/data/config.json`
- لاگ‌ها: `/opt/sahar-agent/logs/`

### Xray
- فایل کانفیگ: `/usr/local/etc/xray/config.json`
- لاگ‌ها: `/var/log/xray/`

---

## مشاهده لاگ و عیب‌یابی | Logs and troubleshooting

### Debian/Ubuntu
```bash
journalctl -u sahar-master-bot -n 100 --no-pager
journalctl -u sahar-master-scheduler -n 100 --no-pager
journalctl -u sahar-master-subscription -n 100 --no-pager
journalctl -u sahar-master-local-agent -n 100 --no-pager
journalctl -u sahar-agent -n 100 --no-pager
journalctl -u xray -n 100 --no-pager
```

### Alpine
```bash
tail -n 100 /opt/sahar-master/logs/*.log
tail -n 100 /opt/sahar-agent/logs/*.log
tail -n 100 /var/log/xray/*
```

نکته: اگر Local Node روی Master فعال نشده باشد، طبیعی است که سرویس `sahar-master-local-agent` وجود نداشته باشد.

---

## از داخل بات چه کارهایی می‌توانی انجام بدهی؟ | Telegram bot capabilities

مواردی که در کد پروژه برای بات دیده می‌شود:

- ساخت، حذف، فعال و غیرفعال کردن کاربر
- تغییر زمان و حجم
- ریست مصرف
- مشاهده subscription
- گرفتن لینک یا QR کاربر
- مدیریت دسترسی کاربر به سرورها
- افزودن سرور جدید با SSH wizard
- مشاهده وضعیت سلامت سرورها
- بررسی خطاهای اخیر
- مدیریت پلن‌ها
- مدیریت ادمین‌ها و نقش‌ها
- گرفتن backup

نقش‌های ادمین در پروژه:

- `owner`
- `admin`
- `support`
- `viewer`

برای بعضی عملیات حساس، بات از **مرحله تأیید** استفاده می‌کند. این مورد به معنی سیستم احراز هویت دومرحله‌ای کامل نیست؛ فقط یک مرحله تأیید برای عملیات مخرب است.

---

## افزودن Agent با SSH | SSH provisioning

یکی از قابلیت‌های مهم پروژه این است که Master می‌تواند از داخل بات، Agent را روی VPS جدید نصب کند.

اطلاعاتی که در wizard از شما گرفته می‌شود:

- نام سرور
- IP یا دامنه SSH
- پورت SSH
- نام کاربری SSH
- رمز SSH

بعد Master این کارها را انجام می‌دهد:

- اتصال SSH برقرار می‌کند
- فایل‌های پروژه را به سرور مقصد می‌فرستد
- نصب Agent را اجرا می‌کند
- health check می‌گیرد
- سرور را در دیتابیس ثبت می‌کند
- در صورت فعال بودن Cloudflare، رکورد DNS را هم می‌سازد

---

## Cloudflare به چه شکل کار می‌کند؟ | Cloudflare automation

اگر Cloudflare را هنگام نصب Master فعال کنی، پروژه می‌تواند برای نودها رکورد DNS بسازد.

ورودی‌های اصلی:

- دامنه اصلی، مثلاً `example.com`
- base subdomain اختیاری، مثلاً `vpn`
- نام سرور، مثلاً `ir1`

نمونه خروجی:

```text
ir1.vpn.example.com
```

اگر بعداً سرور از سیستم حذف شود، پروژه تلاش می‌کند رکورد DNS مربوط به آن را هم پاک کند.

---

## حداقل منابع پیشنهادی | Suggested minimum resources

### Master فقط مدیریتی
- 1 vCPU
- 1 GB RAM
- 10 GB SSD

### Master + Local Node
- 2 vCPU
- 2 GB RAM
- 20 GB SSD

### Agent
- 1 vCPU
- 1 GB RAM
- 10 GB SSD

این اعداد توصیه عملی هستند، نه محدودیت سخت کد.

---

## نکات امنیتی مهم | Security notes

- برای Cloudflare فقط دسترسی‌های لازم را بده:
  - `Zone Read`
  - `DNS Write`
- برای Agent بهتر است `Allowed source IPs/CIDRs` را روی IP مستر تنظیم کنی، نه روی حالت باز
- توکن Agent را طولانی و تصادفی نگه دار
- بعد از نصب، وضعیت این سرویس‌ها را چک کن:
  - `sahar-master-bot`
  - `sahar-master-scheduler`
  - `sahar-master-subscription`
  - `sahar-agent`
  - `xray`
- اگر از دامنه استفاده می‌کنی، قبل از ادامه نصب مطمئن شو A record درست به IP سرور اشاره می‌کند

---

## ساختار فایل‌ها | Project tree

```text
install.sh
install_master.sh
install_agent.sh
master_app/
  agent_client.py
  backup_manager.py
  bootstrap_cloudflare.py
  cloudflare_manager.py
  bot.py
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
assets/
  banner.png
  master-install.png
  agent-install.png
VERSION
LICENSE
README.md
PATCH_NOTES.txt
```

---

## نمای نصب | Installation preview

### نصب Master
<p align="center">
  <img src="assets/master-install.png" alt="Master install" width="85%">
</p>

### نصب Agent
<p align="center">
  <img src="assets/agent-install.png" alt="Agent install" width="85%">
</p>

---

## خلاصه انگلیسی | English summary

Sahar is a Telegram-first Xray/VLESS management bundle with a master-agent design.

- Use `install.sh` to start.
- Install `master` on the main server.
- Install `agent` on extra nodes.
- Supported OS families: Debian/Ubuntu and Alpine.
- Master runs bot, scheduler, subscription service and optional local node.
- Agent exposes an API for Xray operations and node health checks.
- Cloudflare DNS automation is optional.
- SSH provisioning from the Telegram bot is supported.

Quick commands:

```bash
sudo sh install.sh master
sudo sh install.sh agent
```

---

## جمع‌بندی | Final note

اگر بخواهی خیلی خلاصه شروع کنی:

1. فایل را روی سرور باز کن
2. وارد پوشه پروژه شو
3. `install.sh` را اجرا کن
4. برای سرور اصلی `master` بزن
5. برای نودهای اضافه `agent` بزن

اگر فقط یک سرور داری، معمولاً نصب **Master + Local Node** بهترین انتخاب است.
