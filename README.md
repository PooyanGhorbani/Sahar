# سحر 0.1.23

![Sahar banner](assets/banner.png)

**سامانه مدیریت Xray / VLESS با معماری Master / Agent و پنل تلگرام**  
**Telegram-first Xray / VLESS management platform with master-agent architecture**

![version](https://img.shields.io/badge/version-0.1.23-8b5cf6)
![platform](https://img.shields.io/badge/linux-Debian%20%7C%20Ubuntu%20%7C%20Alpine-0ea5e9)
![profiles](https://img.shields.io/badge/VLESS-Reality%20%2B%20Simple-22c55e)
![panel](https://img.shields.io/badge/Panel-Telegram-2563eb)

> **نکته مهم:** این پروژه فقط روی **Ubuntu / Debian / Alpine** پشتیبانی می‌شود و نصب باید با **دسترسی root** انجام شود.  
> **Important:** This project supports **Ubuntu / Debian / Alpine** only and installation must run with **root** privileges.

---

## معرفی پروژه | Project overview

**سحر** برای این ساخته شده که مدیریت Xray را از حالت دستی بیرون بیاورد و آن را به یک جریان متمرکز تبدیل کند.

اجزای اصلی پروژه:
- **Master** برای مدیریت مرکزی، دیتابیس، بات و subscription
- **Agent** برای اعمال تغییرات Xray روی هر VPS
- **Telegram Bot** برای مدیریت روزمره
- **Subscription ثابت** برای هر کاربر
- **Cloudflare DNS automation** به‌صورت اختیاری
- **SSH provisioning** برای نصب Agent از داخل بات

در معماری واقعی پروژه:
- Master مرکز کنترل است
- Agent روی هر نود اجرا می‌شود
- بات تلگرام به Master وصل است
- هر کاربر یک subscription token ثابت دارد
- در حالت `dual`، subscription هر دو پروفایل Simple و Reality را برمی‌گرداند

---

## این بسته شامل چه چیزهایی است؟ | Bundle contents

این فایل ZIP شامل این موارد است:
- `install.sh` شروع نصب
- `install_master.sh` نصب Master
- `install_agent.sh` نصب Agent
- `master_app/` کدهای Master
- `agent_app/` کدهای Agent
- `assets/` فایل‌های تصویری README
- `VERSION` نسخه بسته
- `PATCH_NOTES.txt` یادداشت تغییرات

---

## نصب از روی فایل ZIP | Install from the ZIP bundle

اگر همین بسته را دانلود کرده‌ای، روش استاندارد نصب این است:

```bash
unzip sahar_0.1.23_single_installer.zip && cd sahar_0.1.23_single_installer && sudo sh install.sh
```

برای نصب مستقیم Master:

```bash
unzip sahar_0.1.23_single_installer.zip && cd sahar_0.1.23_single_installer && sudo sh install.sh master
```

برای نصب مستقیم Agent:

```bash
unzip sahar_0.1.23_single_installer.zip && cd sahar_0.1.23_single_installer && sudo sh install.sh agent
```

اگر آرگومان ندهی، installer به‌صورت پیش‌فرض `master` را نصب می‌کند و سؤالی نمی‌پرسد.

---


## نصب مستقیم از GitHub با یک خط دستور | One-line direct install from GitHub

آدرس واقعی پروژه:

```text
https://github.com/PooyanGhorbani/Sahar
```

این دستورها قبل از clone شدن، اگر `git` روی سرور نباشد آن را خودکار نصب می‌کنند.

### نصب Master از GitHub

```bash
sh -c 'set -e; if ! command -v git >/dev/null 2>&1; then if [ -f /etc/alpine-release ]; then apk add --no-cache git bash curl unzip ca-certificates; else apt-get update && apt-get install -y git bash curl unzip ca-certificates; fi; fi; rm -rf /opt/sahar && git clone https://github.com/PooyanGhorbani/Sahar.git /opt/sahar && cd /opt/sahar && BOT_TOKEN="123456:ABCDEF" sh install.sh master'
```

برای نصب بدون سؤال، فقط `BOT_TOKEN` را از قبل در همان دستور بگذار. اگر `ADMIN_CHAT_IDS` را نگذاری، اولین چت خصوصی که بات را باز کند خودکار **Owner** می‌شود.

```bash
sh -c 'set -e; if ! command -v git >/dev/null 2>&1; then if [ -f /etc/alpine-release ]; then apk add --no-cache git bash curl unzip ca-certificates; else apt-get update && apt-get install -y git bash curl unzip ca-certificates; fi; fi; rm -rf /opt/sahar && git clone https://github.com/PooyanGhorbani/Sahar.git /opt/sahar && cd /opt/sahar && BOT_TOKEN="123456:ABCDEF" ADMIN_CHAT_IDS="123456789" sh install.sh master'
```


### نصب Agent از GitHub

```bash
sh -c 'set -e; if ! command -v git >/dev/null 2>&1; then if [ -f /etc/alpine-release ]; then apk add --no-cache git bash curl unzip ca-certificates; else apt-get update && apt-get install -y git bash curl unzip ca-certificates; fi; fi; rm -rf /opt/sahar && git clone https://github.com/PooyanGhorbani/Sahar.git /opt/sahar && cd /opt/sahar && sh install.sh agent'
```

نصب Agent کاملاً بدون سؤال انجام می‌شود و این موارد را خودش پر می‌کند:
- `public_host` با تشخیص خودکار IP/hostname
- `agent_name` از روی hostname
- `allowed_sources` از روی IP اتصال SSH در صورت وجود
- `agent_token` به‌صورت خودکار


### نکته مهم

- دستورها را با کاربر `root` اجرا کن
- اگر `git` نصب نباشد، خود دستور آن را نصب می‌کند
- اگر مسیر `/opt/sahar` را نمی‌خواهی، آن را با مسیر دلخواه خودت عوض کن
- برای آپدیت بعدی هم می‌توانی دوباره همین دستور را اجرا کنی

## سیستم‌عامل‌های پشتیبانی‌شده | Supported operating systems

این installer خانواده سیستم‌عامل را خودکار تشخیص می‌دهد:
- **Ubuntu / Debian**
- **Alpine**

همچنین ابزار سرویس مناسب را خودش انتخاب می‌کند:
- روی Debian/Ubuntu از `systemd`
- روی Alpine از `OpenRC`

یعنی لازم نیست برای systemd یا OpenRC چیزی را دستی تغییر بدهی.

---

## معماری پروژه | Architecture

### Master
Master این بخش‌ها را اجرا می‌کند:
- Telegram Bot
- SQLite Database
- Subscription HTTP Service
- Scheduler
- Backup Manager
- Cloudflare bootstrap/manager
- SSH Provisioner

Master می‌تواند فقط نقش مدیریتی داشته باشد یا در زمان نصب، به‌صورت اختیاری Local Node هم روی همان سرور فعال شود.

### Agent
Agent روی هر VPS اجرا می‌شود و این کارها را انجام می‌دهد:
- مدیریت کاربران Xray
- فعال/غیرفعال کردن کاربر
- حذف و اضافه کاربر
- بازخوانی و ری‌استارت Xray
- خواندن آمار مصرف از Xray API
- گزارش سلامت نود به Master

### پنل تلگرام | Telegram panel
بات تلگرام برای عملیات روزمره استفاده می‌شود؛ مثل:
- ساخت کاربر
- تغییر پلن
- گرفتن لینک و QR
- افزودن سرور
- بررسی سلامت
- حذف سرور
- اجرای بعضی عملیات نگهداری

---

## پروفایل‌ها و خروجی کاربر | User profiles and output

برای هر کاربر یک **subscription ثابت** ساخته می‌شود. این یعنی:
- لینک subscription کاربر ثابت می‌ماند
- با اضافه یا حذف شدن سرورها، خود لینک عوض نمی‌شود
- فقط محتوای subscription به‌روزرسانی می‌شود

پروفایل‌هایی که پروژه می‌سازد:
- `VLESS | Simple`
- `VLESS | Reality`

در نسخه فعلی:
- subscription هر دو پروفایل را ارائه می‌کند
- لینک و QR اصلی در حالت `dual` روی پروفایل Reality قرار می‌گیرند

---

## شروع سریع | Quick start

### حالت 1: فقط یک VPS داری
اگر فقط یک سرور داری، معمولاً بهترین حالت این است که **Master** را نصب کنی. Local Node در نسخه فعلی به‌صورت پیش‌فرض خاموش است و بعداً می‌توانی آن را فعال کنی.

```bash
unzip sahar_0.1.23_single_installer.zip && cd sahar_0.1.23_single_installer && sudo sh install.sh master
```


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


## نصب بدون سؤال | Non-interactive installation

از این نسخه به بعد installer به‌صورت پیش‌فرض **interactive نیست** و سؤالی نمی‌پرسد.

### Master
مقادیر پیش‌فرض Master:
- `BOT_TOKEN` از environment گرفته می‌شود. اگر خالی باشد، سرویس بات و scheduler شروع نمی‌شوند.
- `ADMIN_CHAT_IDS` اختیاری است. اگر خالی بماند، اولین چت خصوصی که بات را باز کند خودکار **Owner** می‌شود.
- `scheduler_interval_seconds = 300`
- `agent_timeout_seconds = 15`
- `warn_days_left = 3`
- `warn_usage_percent = 80`
- `backup_interval_hours = 24`
- `backup_retention = 10`
- `subscription_bind_host = 0.0.0.0`
- `subscription_bind_port = 8090`
- `subscription_base_url` اگر ممکن باشد از IP عمومی سرور ساخته می‌شود
- `cloudflare_enabled = false`
- `local_node_enabled = false`

نمونه نصب بدون سؤال:

```bash
BOT_TOKEN="123456:ABCDEF" sh install.sh master
```

نمونه نصب با owner از پیش مشخص:

```bash
BOT_TOKEN="123456:ABCDEF" ADMIN_CHAT_IDS="123456789" sh install.sh master
```

### Agent
مقادیر پیش‌فرض Agent:
- `public_host` از IP عمومی یا hostname تشخیص داده می‌شود
- `agent_name` از روی hostname ساخته می‌شود
- `transport_mode = dual`
- `reality_server_name = www.cloudflare.com`
- `reality_dest = www.cloudflare.com:443`
- `fingerprint = chrome`
- `xray_port = 443`
- `reality_port = 8443`
- `xray_api_port = 10085`
- `agent_listen_host = 0.0.0.0`
- `agent_listen_port = 8787`
- `allowed_sources` اگر IP اتصال SSH پیدا شود روی همان IP قفل می‌شود، وگرنه باز می‌ماند
- `agent_token` خودکار ساخته می‌شود

نمونه نصب بدون سؤال:

```bash
sh install.sh agent
```

اگر خواستی هر مقدار را override کنی، فقط به‌صورت environment variable قبل از دستور بگذار:

```bash
PUBLIC_HOST="vpn.example.com" AGENT_LISTEN_PORT="9797" sh install.sh agent
```



## مدیریت بعد از نصب | Post-install management

- بیشتر تنظیمات عملیاتی را بعد از نصب می‌توانی از داخل تلگرام تغییر بدهی.
- اگر `BOT_TOKEN` را هنگام نصب Master نداده باشی، اول آن را در فایل `config.json` بگذار و بعد سرویس‌های بات و scheduler را start کن.
- برای Agent هم هر مقدار را می‌توانی با environment variable یا با ویرایش فایل config تغییر بدهی.
