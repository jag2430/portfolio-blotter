# Portfolio Blotter Dashboard

A real-time portfolio monitoring dashboard built with Python Dash that subscribes to Redis pub/sub channels from the FIX Client application.

## Features

- **Real-time Position Monitoring**: Live updates via Redis pub/sub subscription
- **Portfolio Summary**: Total market value, unrealized/realized P&L
- **Position Table**: Detailed view of all open positions with P&L
- **Executions Blotter**: Real-time execution reports
- **Orders View**: Track all orders and their status
- **P&L Analysis Charts**: Visual breakdown of portfolio performance
- **Dark Theme**: Professional trading terminal aesthetic

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Portfolio Blotter (Dash)                     │
│                     http://localhost:8050                       │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Positions   │  │ Executions  │  │ P&L Charts              │  │
│  │ Table       │  │ Blotter     │  │ (Plotly)                │  │
│  └──────┬──────┘  └──────┬──────┘  └────────────┬────────────┘  │
│         │                │                      │               │
│         ▼                ▼                      ▼               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │           Redis Subscriber (Background Thread)          │    │
│  │  Channels: positions:updates, executions:updates,       │    │
│  │            orders:updates                               │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │     Redis       │
                    │  (Pub/Sub)      │
                    │  localhost:6379 │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   FIX Client    │
                    │  (Spring Boot)  │
                    │  localhost:8081 │
                    └─────────────────┘
```

## Prerequisites

- Python 3.10+
- Redis server (running on localhost:6379)
- FIX Client application (running on localhost:8081)

## Installation

1. Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment (optional):

```bash
cp .env.example .env
# Edit .env with your settings
```

## Running the Dashboard

1. Ensure Redis is running:

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
# Or use docker-compose from the FIX Client project
```

2. Ensure the FIX Client is running on port 8081

3. Start the dashboard:

```bash
python app.py
```

4. Open your browser to http://localhost:8050

## Configuration

Environment variables (can be set in `.env` file):

| Variable | Description | Default |
|----------|-------------|---------|
| `FIX_CLIENT_URL` | FIX Client REST API URL | http://localhost:8081 |
| `REDIS_HOST` | Redis server host | localhost |
| `REDIS_PORT` | Redis server port | 6379 |
| `REDIS_PASSWORD` | Redis password (if any) | (empty) |
| `DASH_DEBUG` | Enable debug mode | true |
| `DASH_HOST` | Dashboard host | 0.0.0.0 |
| `DASH_PORT` | Dashboard port | 8050 |

## Redis Channels

The dashboard subscribes to these Redis pub/sub channels:

| Channel | Description |
|---------|-------------|
| `positions:updates` | Position changes (quantity, P&L, market value) |
| `executions:updates` | New execution reports |
| `orders:updates` | Order status changes |

## Dashboard Tabs

### Positions Tab
- Real-time position table with symbol, quantity, avg cost, current price, market value, P&L
- Pie chart showing position distribution by market value
- Color-coded P&L values (green for profit, red for loss)

### Executions Tab
- Live execution blotter showing all fills
- Color-coded buy/sell indicators
- Shows execution type, quantity, price, and cumulative fills

### Orders Tab
- All orders with current status
- Status indicators: NEW, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED
- Shows order details including leaves quantity

### P&L Analysis Tab
- Bar chart of unrealized P&L by position
- Color-coded bars (green positive, red negative)

## Data Flow

1. **Initial Load**: On startup, the dashboard fetches current portfolio state from FIX Client REST API
2. **Real-time Updates**: Background thread subscribes to Redis pub/sub channels
3. **UI Refresh**: Dash interval callback refreshes UI every second with latest data

## Troubleshooting

### "Disconnected" Status
- Check Redis is running: `redis-cli ping`
- Verify FIX Client is running and connected to Redis

### No Position Data
- Ensure FIX Client has processed some orders
- Check FIX Client logs for execution reports
- Try sending a test order through the FIX Client API

### Charts Not Showing
- Positions need market value data
- Update positions with market prices via FIX Client API:
  ```bash
  curl -X POST http://localhost:8081/api/portfolio/positions/AAPL/price \
    -H "Content-Type: application/json" \
    -d '{"price": 150.00}'
  ```

## Development

Run with auto-reload:

```bash
python app.py  # debug=True is enabled by default
```

## License

MIT
