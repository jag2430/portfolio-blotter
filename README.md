# Portfolio Blotter Dashboard

A real-time portfolio monitoring dashboard built with Python Dash that subscribes to Redis pub/sub channels from the FIX Client application for live position tracking, P&L analysis, and execution monitoring.

## Overview

The Portfolio Blotter provides a comprehensive view of trading activity and portfolio performance. It receives real-time updates via Redis pub/sub, eliminating the need for polling and ensuring instant visibility into position changes, executions, and market data updates.

## Features

### Real-Time Data via Redis Pub/Sub
- **No Polling Required**: Background thread subscribes to Redis channels
- **Instant Updates**: Position, execution, and order changes appear immediately
- **Thread-Safe State**: `PortfolioState` class manages concurrent access

### Multi-Tab Dashboard

#### 1. Positions Tab
- Real-time position table with:
  - Symbol, Quantity, Average Cost
  - Current Price, Market Value
  - Unrealized P&L ($ and %)
  - Realized P&L
- **Pie Chart**: Position distribution by market value
- **Color-coded P&L**: Green for profit, red for loss

#### 2. Executions Tab
- Live execution blotter showing all fills
- Columns: ExecId, ClOrdId, Symbol, Side, ExecType, LastQty, LastPx, CumQty, AvgPx
- Color-coded: Green for BUY, Red for SELL
- Auto-scrolls to show newest executions

#### 3. Orders Tab
- All orders with current status
- Status indicators with colors:
  - NEW (blue)
  - PARTIALLY_FILLED (yellow)
  - FILLED (green)
  - CANCELLED (gray)
  - REJECTED (red)
- Shows order details including leaves quantity

#### 4. P&L Analysis Tab
- **Bar Chart**: Unrealized P&L by position
  - Green bars for profitable positions
  - Red bars for losing positions
- **Summary Statistics**: Total P&L metrics

#### 5. Market Data Tab
- Live prices for all subscribed symbols
- Shows: Symbol, Price, Change, Change %, Bid, Ask
- Source and timestamp of last update

### Summary Cards
Displayed at the top of every tab:
- **Total Market Value**: Sum of all position values
- **Unrealized P&L**: Paper profit/loss across all positions
- **Realized P&L**: Locked-in profit/loss from closed trades
- **Connection Status**: Redis subscription status

### Visual Design
- **Dark Theme**: Professional trading terminal aesthetic
- **Color Coding**: Consistent use of green (profit/buy) and red (loss/sell)
- **Auto-Refresh**: Dashboard updates every second via Dash interval

## Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        Portfolio Blotter Dashboard                         │
│                          http://localhost:8060                             │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                         Dashboard Layout                              │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │ │
│  │  │                    Summary Cards Row                            │  │ │
│  │  │  [Market Value] [Unrealized P&L] [Realized P&L] [Status]        │  │ │
│  │  └─────────────────────────────────────────────────────────────────┘  │ │
│  │                                                                       │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │ │
│  │  │                         Tab Navigation                          │  │ │
│  │  │  [Positions] [Executions] [Orders] [P&L Analysis] [Market Data] │  │ │
│  │  └─────────────────────────────────────────────────────────────────┘  │ │
│  │                                                                       │ │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │ │
│  │  │                        Tab Content                              │  │ │
│  │  │                                                                 │  │ │
│  │  │   Positions Tab:    [Position Table] [Pie Chart]                │  │ │
│  │  │   Executions Tab:   [Executions DataTable]                      │  │ │
│  │  │   Orders Tab:       [Orders DataTable]                          │  │ │
│  │  │   P&L Analysis:     [Bar Chart] [Statistics]                    │  │ │
│  │  │   Market Data:      [Prices DataTable]                          │  │ │
│  │  │                                                                 │  │ │
│  │  └─────────────────────────────────────────────────────────────────┘  │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                        Application Layer                              │ │
│  │                                                                       │ │
│  │  ┌─────────────────────┐         ┌─────────────────────────────────┐  │ │
│  │  │   PortfolioState    │◀───────         Dash Callbacks               
│  │  │   (Thread-safe)     │         │     (1-second interval)         │  │ │
│  │  │                     │         └─────────────────────────────────┘  │ │
│  │  │  • positions: {}    │                                              │ │
│  │  │  • executions: []   │                                              │ │
│  │  │  • orders: {}       │                                              │ │
│  │  │  • market_data: {}  │                                              │ │
│  │  │  • lock: Lock()     │                                              │ │
│  │  └──────────┬──────────┘                                              │ │
│  │             │                                                         │ │
│  │             │ Updates                                                 │ │
│  │             │                                                         │ │
│  │  ┌──────────▼───────────┐                                             │ │
│  │  │   RedisSubscriber    │                                             │ │
│  │  │  (Background Thread) │                                             │ │
│  │  │                      │                                             │ │
│  │  │  Subscribes to:      │                                             │ │
│  │  │  • positions:updates │                                             │ │
│  │  │  • executions:update |                                             │ │
│  │  │  • orders:updates    │                                             │ │
│  │  └──────────┬───────────┘                                             │ │
│  └─────────────┼─────────────────────────────────────────────────────────┘ │
│                │                                                           │
└────────────────┼───────────────────────────────────────────────────────────┘
                 │
                 │ Redis Pub/Sub
                 ▼
        ┌─────────────────┐
        │     Redis       │
        │  localhost:6379 │
        └────────┬────────┘
                 │
                 │ Published by
                 ▼
        ┌─────────────────┐
        │   FIX Client    │
        │  localhost:8081 │
        └─────────────────┘
```

## Data Flow

### Initial Load
1. Dashboard starts and connects to Redis
2. Fetches current portfolio state from FIX Client REST API
3. Background thread subscribes to Redis pub/sub channels

### Real-Time Updates
1. FIX Client receives execution from exchange
2. FIX Client publishes to Redis channel (e.g., `executions:updates`)
3. RedisSubscriber thread receives message
4. `handle_message()` routes to appropriate state update method
5. PortfolioState updates internal data structures (thread-safe)
6. Dash interval callback fires every second
7. Callbacks read from PortfolioState and update UI components

## Redis Channels

| Channel | Message Type | Content | UI Update |
|---------|--------------|---------|-----------|
| `positions:updates` | POSITION_UPDATE | Position with P&L | Positions table, charts |
| `executions:updates` | EXECUTION | Execution details | Executions table |
| `orders:updates` | ORDER_* | Order status | Orders table |
| `marketdata:updates` | MARKET_DATA | Price update | Market Data table, P&L |

### Message Format Examples

**Position Update:**
```json
{
  "type": "POSITION_UPDATE",
  "data": {
    "symbol": "AAPL",
    "quantity": 100,
    "avgCost": 150.25,
    "currentPrice": 155.00,
    "marketValue": 15500.00,
    "unrealizedPnl": 475.00,
    "realizedPnl": 0.00
  }
}
```

**Execution Update:**
```json
{
  "type": "EXECUTION",
  "data": {
    "execId": "EXEC123",
    "clOrdId": "ABC123",
    "symbol": "AAPL",
    "side": "BUY",
    "execType": "FILL",
    "lastPrice": 150.25,
    "lastQuantity": 100,
    "cumQuantity": 100,
    "leavesQuantity": 0
  }
}
```

**Order Update:**
```json
{
  "type": "ORDER_FILLED",
  "data": {
    "clOrdId": "ABC123",
    "symbol": "AAPL",
    "side": "BUY",
    "orderType": "LIMIT",
    "quantity": 100,
    "price": 150.00,
    "status": "FILLED",
    "filledQuantity": 100
  }
}
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

### Dependencies

Key Python packages:
- `dash` - Web framework
- `dash-mantine-components` - UI components
- `dash-bootstrap-components` - Additional components
- `plotly` - Interactive charts
- `pandas` - Data manipulation
- `redis` - Redis client

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

4. Open your browser to http://localhost:8060

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FIX_CLIENT_URL` | FIX Client REST API URL | http://localhost:8081 |
| `REDIS_HOST` | Redis server host | localhost |
| `REDIS_PORT` | Redis server port | 6379 |
| `REDIS_PASSWORD` | Redis password (if any) | (empty) |
| `DASH_DEBUG` | Enable debug mode | true |
| `DASH_HOST` | Dashboard host | 0.0.0.0 |
| `DASH_PORT` | Dashboard port | 8060 |

### Configuration in Code

```python
# app.py configuration

# FIX Client API
FIX_CLIENT_URL = os.getenv("FIX_CLIENT_URL", "http://localhost:8081")

# Redis connection
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Dashboard refresh interval (milliseconds)
REFRESH_INTERVAL_MS = 1000  # 1 second

# Dashboard port
DASH_PORT = int(os.getenv("DASH_PORT", 8060))
```

## Visualizations

### Position Distribution Pie Chart
- Shows allocation of portfolio by market value
- Each slice represents one position
- Hover for details (symbol, value, percentage)

### P&L Bar Chart
- Horizontal bar chart of unrealized P&L by position
- Green bars: Profitable positions
- Red bars: Losing positions
- Sorted by P&L value (best to worst)

### Color Coding Reference

| Element | Green | Red | Yellow | Gray |
|---------|-------|-----|--------|------|
| Side | BUY | SELL | - | - |
| P&L | Profit | Loss | - | - |
| Status | FILLED | REJECTED | PARTIAL | CANCELLED |
| ExecType | FILL | REJECTED | PARTIAL_FILL | CANCELLED |

## Project Structure

```
portfolio-blotter/
├── app.py                 # Main application
├── requirements.txt       # Python dependencies
├── .env.example          # Example environment config
├── .env                  # Local environment config (git-ignored)
└── assets/
    └── styles.css        # Custom CSS styles
```

### Key Classes

**PortfolioState**
```python
class PortfolioState:
    """Thread-safe state management for portfolio data"""
    
    def __init__(self):
        self.positions = {}      # symbol -> Position
        self.executions = []     # List of executions
        self.orders = {}         # clOrdId -> Order
        self.market_data = {}    # symbol -> MarketData
        self.lock = threading.Lock()
    
    def update_position(self, position_data):
        with self.lock:
            self.positions[position_data['symbol']] = position_data
    
    def add_execution(self, execution_data):
        with self.lock:
            self.executions.append(execution_data)
    
    def get_positions_df(self):
        with self.lock:
            return pd.DataFrame(list(self.positions.values()))
```

**RedisSubscriber**
```python
class RedisSubscriber(threading.Thread):
    """Background thread for Redis pub/sub"""
    
    def __init__(self, state: PortfolioState):
        self.state = state
        self.pubsub = redis_client.pubsub()
        self.pubsub.subscribe(
            'positions:updates',
            'executions:updates', 
            'orders:updates',
            'marketdata:updates'
        )
    
    def run(self):
        for message in self.pubsub.listen():
            if message['type'] == 'message':
                self.handle_message(message)
```

## Troubleshooting

### "Disconnected" Status
- Check Redis is running: `redis-cli ping`
- Verify FIX Client is running and connected to Redis
- Check network connectivity to Redis

### No Position Data
- Ensure FIX Client has processed some orders
- Check FIX Client logs for execution reports
- Try sending a test order through the FIX Client API
- Verify positions endpoint: `curl http://localhost:8081/api/portfolio/positions`

### Charts Not Showing
- Positions need market value data
- Ensure positions have currentPrice populated
- Check browser console for JavaScript errors

### Stale Data
- Redis subscriber may have disconnected
- Restart the blotter application
- Check Redis pub/sub: `redis-cli SUBSCRIBE positions:updates`

### High CPU Usage
- Reduce refresh interval in configuration
- Check for excessive console logging
- Verify Redis connection is stable

## Development

### Run with Auto-Reload

```bash
python app.py  # debug=True is enabled by default
```

### Debug Redis Messages

```bash
# Subscribe to all channels and see messages
redis-cli PSUBSCRIBE "*:updates"
```

### Manual State Refresh

```bash
# Force fetch positions from API
curl http://localhost:8081/api/portfolio/positions

# Force fetch executions
curl http://localhost:8081/api/executions
```

## Integration with System

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Trading UI      ───▶    FIX Client      ───▶    Exchange      
│  (Dash:8050)    │REST │ (Spring:8081)   │ FIX │  (Spring:9876)  │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                                 │ Publishes to Redis
                                 ▼
                        ┌─────────────────┐
                        │     Redis       │
                        │    (6379)       │
                        └────────┬────────┘
                                 │
                                 │ Subscribes
                                 ▼
                        ┌─────────────────┐
                        │Portfolio Blotter│
                        │  (Dash:8060)    │
                        └─────────────────┘
```