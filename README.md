# Telegram Controller Automation

A production-quality Telegram automation application that identifies inactive Telegram groups based on user-defined date and time thresholds, and sends automated messages to those groups.

## Features

- **Telegram Integration**: Secure authentication using Telegram API with Telethon
- **Group Scanning**: Automatically scans all Telegram groups the user belongs to
- **Inactivity Detection**: Configurable date/time threshold to identify inactive groups
- **Automated Messaging**: Send custom messages with rate limiting and delays
- **Modern UI**: Apple Human Interface Guidelines-inspired design
- **Deployable on Railway**: Docker-based deployment ready for Railway

## Architecture

```
project/
├── backend/
│   ├── telegram_client/    # Telegram API authentication and client
│   ├── group_scanner/      # Scans groups and retrieves metadata
│   ├── inactivity_filter/  # Filters groups by inactivity threshold
│   ├── message_sender/     # Automated message sending
│   └── scheduler/          # Optional scheduled automation
├── frontend/
│   ├── pages/             # HTML templates
│   ├── styles/            # CSS stylesheets
│   └── scripts/           # JavaScript application
├── config/               # Configuration management
├── logs/                 # Application logs
├── data/                 # Data storage
├── main.py               # Flask application entry point
├── requirements.txt      # Python dependencies
├── Dockerfile            # Docker configuration
├── railway.toml          # Railway deployment config
└── .env.example          # Environment variables template
```

## Prerequisites

- Python 3.11+
- Telegram API credentials (API_ID and API_HASH)
- Telegram session string

## Getting Telegram Credentials

1. Visit https://my.telegram.org/apps
2. Create a new application
3. Copy the `API_ID` and `API_HASH`

## Local Setup

### 1. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/hangtagsmanager-debug/telegram-controller.git
cd telegram-controller

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your credentials
nano .env
```

### 3. Run the Application

```bash
# Start the server
python main.py
```

The application will be available at http://localhost:5000

## Railway Deployment

### 1. Deploy to Railway

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login to Railway
railway login

# Initialize project
railway init

# Set environment variables
railway variables set API_ID=your_api_id
railway variables set API_HASH=your_api_hash
railway variables set SESSION_STRING=your_session_string

# Deploy
railway up
```

### 2. Environment Variables

Required environment variables for Railway:

| Variable       | Description             |
| -------------- | ----------------------- |
| API_ID         | Telegram API ID         |
| API_HASH       | Telegram API Hash       |
| SESSION_STRING | Telegram session string |

Optional environment variables:

| Variable             | Default | Description                              |
| -------------------- | ------- | ---------------------------------------- |
| DEBUG                | false   | Enable debug mode                        |
| PORT                 | 5000    | Server port                              |
| DEFAULT_DELAY_MIN    | 10      | Minimum delay between messages (seconds) |
| DEFAULT_DELAY_MAX    | 30      | Maximum delay between messages (seconds) |
| MAX_MESSAGES_PER_RUN | 50      | Maximum messages to send per run         |

## Usage Guide

### 1. Authentication

1. Enter your session string in the login modal
2. Click "Connect" to authenticate with Telegram

### 2. Scan Groups

1. Click "Scan Now" to discover all your Telegram groups
2. The scanner will retrieve group information and last message timestamps

### 3. Configure Inactivity Filter

1. Go to the Automation tab
2. Set the date and time threshold
3. Click "Apply Threshold"
4. Groups with last messages before this date will be marked as inactive

### 4. Send Messages

1. Write your message in the message template
2. Configure delay settings (random delay between messages)
3. Optionally enable "Preview Mode" to test without sending
4. Click "Start Automation"

## API Endpoints

| Endpoint                    | Method | Description                 |
| --------------------------- | ------ | --------------------------- |
| `/api/auth/status`          | GET    | Check authentication status |
| `/api/auth/login`           | POST   | Login with session string   |
| `/api/auth/logout`          | POST   | Logout                      |
| `/api/groups/scan`          | POST   | Scan all groups             |
| `/api/groups`               | GET    | Get all groups              |
| `/api/filter/set-threshold` | POST   | Set inactivity threshold    |
| `/api/filter/apply`         | POST   | Apply filter                |
| `/api/automation/send`      | POST   | Send messages               |
| `/api/automation/stop`      | POST   | Stop automation             |
| `/api/dashboard`            | GET    | Get dashboard data          |
| `/api/logs`                 | GET    | Get activity logs           |

## Safety Features

- **Rate Limiting**: Configurable delays between messages
- **Preview Mode**: Test automation without sending messages
- **Stop Button**: Cancel automation at any time
- **Maximum Messages**: Limit messages per run
- **Error Handling**: Automatic retry on failures

## Development

### Running in Debug Mode

```bash
DEBUG=true python main.py
```

### Adding New Features

The modular architecture makes it easy to extend:

- Add new filters in `backend/inactivity_filter/`
- Add new message handlers in `backend/message_sender/`
- Add new UI components in `frontend/`

## License

MIT License

## Support

For issues and questions, please open an issue on GitHub.
