"""
Portfolio Blotter - Real-time Position Monitoring Dashboard
Subscribes to Redis pub/sub channels for live updates from FIX Client
"""

import json
import os
import threading
from datetime import datetime
from decimal import Decimal
from typing import Optional

import dash
from dash import html, dcc, dash_table, callback, Input, Output, State
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import redis
import requests
from dataclasses import dataclass, asdict
from collections import deque
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
FIX_CLIENT_URL = os.getenv("FIX_CLIENT_URL", "http://localhost:8081")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
DASH_DEBUG = os.getenv("DASH_DEBUG", "true").lower() == "true"
DASH_HOST = os.getenv("DASH_HOST", "0.0.0.0")
DASH_PORT = int(os.getenv("DASH_PORT", 8060))

REDIS_CHANNELS = {
    "positions": "positions:updates",
    "executions": "executions:updates",
    "orders": "orders:updates",
    "marketdata": "marketdata:updates"
}


class PortfolioState:
    """Thread-safe state management for portfolio data"""
    
    def __init__(self):
        self.positions = {}
        self.executions = deque(maxlen=100)
        self.orders = {}
        self.portfolio_summary = {}
        self.market_data = {}
        self.last_update = None
        self.connected = False
        self.lock = threading.Lock()
        self.update_log = deque(maxlen=50)  # Track recent updates for debugging
    
    def log_update(self, msg: str):
        """Log update for debugging"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.update_log.appendleft(f"[{timestamp}] {msg}")
        print(f"[{timestamp}] {msg}")
    
    def update_position(self, position_data: dict):
        with self.lock:
            symbol = position_data.get('symbol')
            if symbol:
                self.positions[symbol] = position_data
                self.last_update = datetime.now()
                self.log_update(f"Position updated: {symbol} qty={position_data.get('quantity')} "
                              f"price=${position_data.get('currentPrice', 'N/A')}")
    
    def update_market_data(self, market_data: dict):
        """Update market data and recalculate position P&L"""
        with self.lock:
            symbol = market_data.get('symbol')
            price = market_data.get('price')
            
            if not symbol:
                self.log_update(f"Market data missing symbol: {market_data}")
                return
            
            if price is None:
                self.log_update(f"Market data missing price for {symbol}")
                return
            
            # Convert price to float if needed
            try:
                price = float(price)
            except (TypeError, ValueError):
                self.log_update(f"Invalid price for {symbol}: {price}")
                return
            
            # Store latest market data
            market_data['price'] = price
            market_data['receivedAt'] = datetime.now().isoformat()
            self.market_data[symbol] = market_data
            
            # Update position if exists
            if symbol in self.positions:
                position = self.positions[symbol]
                quantity = position.get('quantity', 0)
                
                # Handle avgCost - could be string or number
                avg_cost = position.get('avgCost', 0)
                try:
                    avg_cost = float(avg_cost) if avg_cost else 0
                except (TypeError, ValueError):
                    avg_cost = 0
                
                # Update current price
                old_price = position.get('currentPrice')
                position['currentPrice'] = price
                
                # Recalculate market value and unrealized P&L
                if quantity != 0:
                    abs_qty = abs(quantity)
                    market_value = price * abs_qty
                    total_cost = avg_cost * abs_qty
                    
                    if quantity > 0:
                        # Long position: profit when price > avg cost
                        unrealized_pnl = market_value - total_cost
                    else:
                        # Short position: profit when price < avg cost
                        unrealized_pnl = total_cost - market_value
                    
                    position['marketValue'] = round(market_value, 2)
                    position['unrealizedPnl'] = round(unrealized_pnl, 2)
                    position['totalCost'] = round(total_cost, 2)
                
                position['lastUpdated'] = datetime.now().isoformat()
                self.positions[symbol] = position
                
                self.log_update(f"Position {symbol} price updated: ${old_price} -> ${price:.2f}, "
                              f"Unrealized P&L: ${position.get('unrealizedPnl', 0):.2f}")
            else:
                self.log_update(f"Market data received for {symbol} @ ${price:.2f} (no position)")
            
            self.last_update = datetime.now()
    
    def add_execution(self, exec_data: dict):
        with self.lock:
            self.executions.appendleft(exec_data)
            self.last_update = datetime.now()
            self.log_update(f"Execution: {exec_data.get('execType')} {exec_data.get('side')} "
                          f"{exec_data.get('symbol')} {exec_data.get('lastQuantity')} @ ${exec_data.get('lastPrice')}")
    
    def update_order(self, order_data: dict):
        with self.lock:
            cl_ord_id = order_data.get('clOrdId')
            if cl_ord_id:
                self.orders[cl_ord_id] = order_data
                self.last_update = datetime.now()
                self.log_update(f"Order: {cl_ord_id} {order_data.get('status')} "
                              f"{order_data.get('side')} {order_data.get('symbol')}")
    
    def get_positions_df(self) -> pd.DataFrame:
        with self.lock:
            if not self.positions:
                return pd.DataFrame()
            df = pd.DataFrame(list(self.positions.values()))
            # Ensure numeric columns are numeric
            numeric_cols = ['quantity', 'avgCost', 'currentPrice', 'marketValue', 
                          'unrealizedPnl', 'realizedPnl', 'totalCost']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            return df
    
    def get_executions_df(self) -> pd.DataFrame:
        with self.lock:
            if not self.executions:
                return pd.DataFrame()
            return pd.DataFrame(list(self.executions))
    
    def get_orders_df(self) -> pd.DataFrame:
        with self.lock:
            if not self.orders:
                return pd.DataFrame()
            return pd.DataFrame(list(self.orders.values()))
    
    def get_market_data_df(self) -> pd.DataFrame:
        with self.lock:
            if not self.market_data:
                return pd.DataFrame()
            df = pd.DataFrame(list(self.market_data.values()))
            # Ensure numeric columns
            numeric_cols = ['price', 'bidPrice', 'askPrice', 'volume', 'open', 'high', 'low']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
    
    def get_update_log(self) -> list:
        with self.lock:
            return list(self.update_log)


# Global state instance
state = PortfolioState()


class RedisSubscriber(threading.Thread):
    """Background thread for Redis pub/sub subscription"""
    
    def __init__(self, state: PortfolioState):
        super().__init__(daemon=True)
        self.state = state
        self.running = False
        self.redis_client = None
        self.pubsub = None
    
    def connect(self):
        try:
            self.redis_client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD if REDIS_PASSWORD else None,
                decode_responses=True
            )
            self.redis_client.ping()
            self.pubsub = self.redis_client.pubsub()
            
            # Subscribe to all channels
            channels = list(REDIS_CHANNELS.values())
            self.pubsub.subscribe(*channels)
            
            self.state.connected = True
            self.state.log_update(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
            self.state.log_update(f"Subscribed to: {channels}")
            return True
        except Exception as e:
            self.state.log_update(f"Failed to connect to Redis: {e}")
            self.state.connected = False
            return False
    
    def run(self):
        self.running = True
        if not self.connect():
            return
        
        while self.running:
            try:
                message = self.pubsub.get_message(timeout=1.0)
                if message and message['type'] == 'message':
                    self.handle_message(message['channel'], message['data'])
            except redis.ConnectionError as e:
                self.state.log_update(f"Redis connection lost: {e}")
                self.state.connected = False
                if not self.connect():
                    import time
                    time.sleep(5)
            except Exception as e:
                self.state.log_update(f"Redis subscriber error: {e}")
    
    def handle_message(self, channel: str, data: str):
        try:
            # Parse the JSON data
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            
            payload = json.loads(data)
            
            # Handle double-encoded JSON
            if isinstance(payload, str):
                payload = json.loads(payload)
            
            msg_type = payload.get('type', '') if isinstance(payload, dict) else ''
            msg_data = payload.get('data', {}) if isinstance(payload, dict) else {}
            
            # Route to appropriate handler
            if channel == REDIS_CHANNELS["positions"]:
                if msg_type == "POSITION_UPDATE":
                    self.state.update_position(msg_data)
            
            elif channel == REDIS_CHANNELS["executions"]:
                if msg_type == "EXECUTION":
                    self.state.add_execution(msg_data)
            
            elif channel == REDIS_CHANNELS["orders"]:
                if isinstance(msg_data, dict) and msg_data:
                    self.state.update_order(msg_data)
            
            elif channel == REDIS_CHANNELS["marketdata"]:
                if msg_type == "MARKET_DATA":
                    self.state.update_market_data(msg_data)
                
        except json.JSONDecodeError as e:
            self.state.log_update(f"JSON parse error: {e}")
        except Exception as e:
            self.state.log_update(f"Message handling error: {e}")
    
    def stop(self):
        self.running = False
        if self.pubsub:
            self.pubsub.close()
        if self.redis_client:
            self.redis_client.close()


# Start Redis subscriber
subscriber = RedisSubscriber(state)
subscriber.start()


def fetch_initial_data():
    """Fetch current portfolio state from FIX Client REST API"""
    try:
        # Fetch portfolio summary with positions
        resp = requests.get(f"{FIX_CLIENT_URL}/api/portfolio/summary", timeout=5)
        if resp.ok:
            summary = resp.json()
            state.portfolio_summary = summary
            for pos in summary.get('positions', []):
                state.update_position(pos)
            state.log_update(f"Loaded {len(summary.get('positions', []))} positions from API")
        
        # Fetch recent executions
        resp = requests.get(f"{FIX_CLIENT_URL}/api/executions?limit=50", timeout=5)
        if resp.ok:
            executions = resp.json()
            for exec_data in executions:
                state.add_execution(exec_data)
            state.log_update(f"Loaded {len(executions)} executions from API")
        
        # Fetch orders
        resp = requests.get(f"{FIX_CLIENT_URL}/api/orders", timeout=5)
        if resp.ok:
            orders = resp.json()
            for order in orders:
                state.update_order(order)
            state.log_update(f"Loaded {len(orders)} orders from API")
        
        # Fetch market data
        try:
            resp = requests.get(f"{FIX_CLIENT_URL}/api/portfolio/market-data", timeout=5)
            if resp.ok:
                md = resp.json()
                quotes = md.get('quotes', {})
                for symbol, quote in quotes.items():
                    state.update_market_data(quote)
                state.log_update(f"Loaded market data for {len(quotes)} symbols")
        except Exception as e:
            state.log_update(f"Could not fetch market data: {e}")
                
    except requests.exceptions.ConnectionError:
        state.log_update(f"Could not connect to FIX Client at {FIX_CLIENT_URL}")
    except Exception as e:
        state.log_update(f"Failed to fetch initial data: {e}")


# Load initial data
fetch_initial_data()


# Create Dash app
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title="Portfolio Blotter"
)

# Custom styles
CARD_STYLE = {
    "backgroundColor": "#303030",
    "borderRadius": "8px",
    "padding": "15px",
    "marginBottom": "15px"
}

# Layout
app.layout = dbc.Container([
    # Header
    dbc.Row([
        dbc.Col([
            html.H1("📊 Portfolio Blotter", style={"color": "#00d4aa"}),
            html.P("Real-time position monitoring with Finnhub market data", 
                   style={"color": "#888"})
        ], width=8),
        dbc.Col([
            html.Div(id="connection-status", style={"textAlign": "right"}),
            html.Div(id="last-update", style={"textAlign": "right", "color": "#888", "fontSize": "12px"})
        ], width=4)
    ], className="mb-4 mt-3"),
    
    # Summary Cards
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("Total Market Value", style={"color": "#888"}),
                    html.H3(id="total-market-value", style={"color": "#00d4aa"})
                ])
            ], style=CARD_STYLE)
        ], width=3),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("Unrealized P&L", style={"color": "#888"}),
                    html.H3(id="unrealized-pnl")
                ])
            ], style=CARD_STYLE)
        ], width=3),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("Realized P&L", style={"color": "#888"}),
                    html.H3(id="realized-pnl")
                ])
            ], style=CARD_STYLE)
        ], width=3),
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H6("Open Positions", style={"color": "#888"}),
                    html.H3(id="position-count", style={"color": "#00d4aa"})
                ])
            ], style=CARD_STYLE)
        ], width=3),
    ], className="mb-4"),
    
    # Main content tabs
    dbc.Tabs([
        dbc.Tab([
            dbc.Row([
                dbc.Col([
                    html.H5("Positions", style={"color": "#00d4aa", "marginTop": "20px"}),
                    html.Div(id="positions-table-container")
                ], width=8),
                dbc.Col([
                    html.H5("Distribution", style={"color": "#00d4aa", "marginTop": "20px"}),
                    html.Div(id="position-chart-container")
                ], width=4)
            ])
        ], label="Positions", tab_id="tab-positions"),
        
        dbc.Tab([
            html.H5("Executions", style={"color": "#00d4aa", "marginTop": "20px"}),
            html.Div(id="executions-table-container")
        ], label="Executions", tab_id="tab-executions"),
        
        dbc.Tab([
            html.H5("Orders", style={"color": "#00d4aa", "marginTop": "20px"}),
            html.Div(id="orders-table-container")
        ], label="Orders", tab_id="tab-orders"),
        
        dbc.Tab([
            html.H5("P&L by Position", style={"color": "#00d4aa", "marginTop": "20px"}),
            html.Div(id="pnl-chart-container")
        ], label="P&L Analysis", tab_id="tab-pnl"),
        
        dbc.Tab([
            html.H5("Live Market Data (Finnhub)", style={"color": "#00d4aa", "marginTop": "20px"}),
            html.Div(id="marketdata-table-container"),
            html.Hr(style={"borderColor": "#444"}),
            html.H6("Subscribe to symbols:", style={"color": "#888", "marginTop": "20px"}),
            dbc.InputGroup([
                dbc.Input(id="subscribe-input", placeholder="AAPL,MSFT,GOOGL", type="text"),
                dbc.Button("Subscribe", id="subscribe-btn", color="success", n_clicks=0)
            ], className="mb-3", style={"maxWidth": "400px"}),
            html.Div(id="subscribe-result", style={"color": "#888"})
        ], label="Market Data", tab_id="tab-marketdata"),
        
        dbc.Tab([
            html.H5("Update Log", style={"color": "#00d4aa", "marginTop": "20px"}),
            html.Div(id="update-log-container", 
                    style={"backgroundColor": "#1a1a1a", "padding": "15px", 
                           "borderRadius": "8px", "fontFamily": "monospace",
                           "fontSize": "12px", "maxHeight": "500px", "overflowY": "auto"})
        ], label="Debug Log", tab_id="tab-debug")
    ], id="tabs", active_tab="tab-positions"),
    
    # Auto-refresh interval
    dcc.Interval(id='interval-component', interval=1000, n_intervals=0),
    dcc.Store(id='portfolio-data')
    
], fluid=True, style={"backgroundColor": "#1a1a1a", "minHeight": "100vh", "padding": "20px"})


# Callbacks
@callback(
    [Output("connection-status", "children"),
     Output("last-update", "children"),
     Output("total-market-value", "children"),
     Output("unrealized-pnl", "children"),
     Output("unrealized-pnl", "style"),
     Output("realized-pnl", "children"),
     Output("realized-pnl", "style"),
     Output("position-count", "children")],
    Input("interval-component", "n_intervals")
)
def update_summary(n):
    # Connection status
    if state.connected:
        conn_status = dbc.Badge("● Connected to Redis", color="success", className="me-1")
    else:
        conn_status = dbc.Badge("● Disconnected", color="danger", className="me-1")
    
    # Last update time
    last_update = ""
    if state.last_update:
        last_update = f"Last update: {state.last_update.strftime('%H:%M:%S')}"
    
    # Calculate totals from positions
    df = state.get_positions_df()
    
    if df.empty:
        return (conn_status, last_update, "$0.00", "$0.00", {"color": "#888"}, 
                "$0.00", {"color": "#888"}, "0")
    
    total_mv = df['marketValue'].sum() if 'marketValue' in df.columns else 0
    total_unrealized = df['unrealizedPnl'].sum() if 'unrealizedPnl' in df.columns else 0
    total_realized = df['realizedPnl'].sum() if 'realizedPnl' in df.columns else 0
    
    # Filter for open positions
    open_count = len(df[df['quantity'] != 0]) if 'quantity' in df.columns else 0
    
    # Format values
    mv_str = f"${total_mv:,.2f}"
    unrealized_str = f"${total_unrealized:+,.2f}"
    realized_str = f"${total_realized:+,.2f}"
    
    # P&L colors
    unrealized_style = {"color": "#00ff88" if total_unrealized >= 0 else "#ff4444"}
    realized_style = {"color": "#00ff88" if total_realized >= 0 else "#ff4444"}
    
    return (conn_status, last_update, mv_str, unrealized_str, unrealized_style,
            realized_str, realized_style, str(open_count))


@callback(
    Output("positions-table-container", "children"),
    Input("interval-component", "n_intervals")
)
def update_positions_table(n):
    df = state.get_positions_df()
    
    if df.empty:
        return html.Div("No positions. Send some orders to get started!", 
                       style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    # Filter open positions
    df = df[df['quantity'] != 0].copy()
    
    if df.empty:
        return html.Div("No open positions", 
                       style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    # Select and order columns
    columns_to_show = ['symbol', 'quantity', 'avgCost', 'currentPrice', 'marketValue', 'unrealizedPnl', 'realizedPnl']
    columns_to_show = [c for c in columns_to_show if c in df.columns]
    
    display_df = df[columns_to_show].copy()
    
    # Format numeric columns for display
    for col in ['avgCost', 'currentPrice', 'marketValue', 'unrealizedPnl', 'realizedPnl']:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(
                lambda x: f"${x:,.2f}" if pd.notnull(x) and x != 0 else "-"
            )
    
    # Column name mapping
    col_names = {
        'symbol': 'Symbol',
        'quantity': 'Qty',
        'avgCost': 'Avg Cost',
        'currentPrice': 'Price',
        'marketValue': 'Mkt Value',
        'unrealizedPnl': 'Unreal P&L',
        'realizedPnl': 'Real P&L'
    }
    
    return dash_table.DataTable(
        data=display_df.to_dict('records'),
        columns=[{"name": col_names.get(col, col), "id": col} for col in columns_to_show],
        style_table={'overflowX': 'auto'},
        style_cell={
            'backgroundColor': '#2d2d2d',
            'color': 'white',
            'textAlign': 'right',
            'padding': '12px',
            'fontFamily': 'monospace'
        },
        style_header={
            'backgroundColor': '#1a1a1a',
            'color': '#00d4aa',
            'fontWeight': 'bold',
            'textAlign': 'center'
        },
        style_data_conditional=[
            {'if': {'column_id': 'symbol'}, 'textAlign': 'left', 'fontWeight': 'bold'},
            {'if': {'column_id': 'quantity'}, 'textAlign': 'center'},
        ]
    )


@callback(
    Output("position-chart-container", "children"),
    Input("interval-component", "n_intervals")
)
def update_position_chart(n):
    df = state.get_positions_df()
    
    if df.empty or 'marketValue' not in df.columns:
        return html.Div("No data", style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    df = df[df['quantity'] != 0].copy()
    df = df[df['marketValue'] > 0]
    
    if df.empty:
        return html.Div("No positions with market value", 
                       style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    fig = px.pie(
        df, values='marketValue', names='symbol',
        color_discrete_sequence=px.colors.qualitative.Set3
    )
    fig.update_layout(
        paper_bgcolor='#303030',
        plot_bgcolor='#303030',
        font_color='white',
        showlegend=True,
        margin=dict(t=20, b=20, l=20, r=20)
    )
    
    return dcc.Graph(figure=fig, style={"height": "350px"})


@callback(
    Output("executions-table-container", "children"),
    Input("interval-component", "n_intervals")
)
def update_executions_table(n):
    df = state.get_executions_df()
    
    if df.empty:
        return html.Div("No executions yet", 
                       style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    columns_to_show = ['timestamp', 'symbol', 'side', 'execType', 'lastQuantity', 'lastPrice', 'cumQuantity', 'orderStatus']
    columns_to_show = [c for c in columns_to_show if c in df.columns]
    
    display_df = df[columns_to_show].head(50).copy()
    
    for col in ['lastPrice', 'avgPrice']:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(
                lambda x: f"${float(x):,.2f}" if pd.notnull(x) and x != 0 else "-"
            )
    
    return dash_table.DataTable(
        data=display_df.to_dict('records'),
        columns=[{"name": col, "id": col} for col in columns_to_show],
        style_table={'overflowX': 'auto'},
        style_cell={
            'backgroundColor': '#2d2d2d',
            'color': 'white',
            'textAlign': 'right',
            'padding': '10px',
            'fontFamily': 'monospace',
            'fontSize': '13px'
        },
        style_header={
            'backgroundColor': '#1a1a1a',
            'color': '#00d4aa',
            'fontWeight': 'bold',
            'textAlign': 'center'
        },
        style_data_conditional=[
            {'if': {'filter_query': '{side} = "BUY"', 'column_id': 'side'}, 'color': '#00ff88'},
            {'if': {'filter_query': '{side} = "SELL"', 'column_id': 'side'}, 'color': '#ff4444'},
            {'if': {'filter_query': '{execType} = "FILL"', 'column_id': 'execType'}, 'color': '#00d4aa', 'fontWeight': 'bold'}
        ]
    )


@callback(
    Output("orders-table-container", "children"),
    Input("interval-component", "n_intervals")
)
def update_orders_table(n):
    df = state.get_orders_df()
    
    if df.empty:
        return html.Div("No orders yet", 
                       style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    columns_to_show = ['clOrdId', 'symbol', 'side', 'orderType', 'quantity', 'price', 'status', 'filledQuantity', 'leavesQuantity']
    columns_to_show = [c for c in columns_to_show if c in df.columns]
    
    display_df = df[columns_to_show].copy()
    
    if 'price' in display_df.columns:
        display_df['price'] = display_df['price'].apply(
            lambda x: f"${float(x):,.2f}" if pd.notnull(x) else "-"
        )
    
    return dash_table.DataTable(
        data=display_df.to_dict('records'),
        columns=[{"name": col, "id": col} for col in columns_to_show],
        style_table={'overflowX': 'auto'},
        style_cell={
            'backgroundColor': '#2d2d2d',
            'color': 'white',
            'textAlign': 'right',
            'padding': '10px',
            'fontFamily': 'monospace',
            'fontSize': '13px'
        },
        style_header={
            'backgroundColor': '#1a1a1a',
            'color': '#00d4aa',
            'fontWeight': 'bold',
            'textAlign': 'center'
        },
        style_data_conditional=[
            {'if': {'filter_query': '{side} = "BUY"', 'column_id': 'side'}, 'color': '#00ff88'},
            {'if': {'filter_query': '{side} = "SELL"', 'column_id': 'side'}, 'color': '#ff4444'},
            {'if': {'filter_query': '{status} = "FILLED"', 'column_id': 'status'}, 'color': '#00d4aa', 'fontWeight': 'bold'},
            {'if': {'filter_query': '{status} = "CANCELLED"', 'column_id': 'status'}, 'color': '#888'},
            {'if': {'filter_query': '{status} = "REJECTED"', 'column_id': 'status'}, 'color': '#ff4444'}
        ]
    )


@callback(
    Output("pnl-chart-container", "children"),
    Input("interval-component", "n_intervals")
)
def update_pnl_chart(n):
    df = state.get_positions_df()
    
    if df.empty:
        return html.Div("No P&L data", 
                       style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    df = df[df['quantity'] != 0].copy()
    
    if df.empty or 'unrealizedPnl' not in df.columns:
        return html.Div("No P&L data available", 
                       style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    colors = ['#00ff88' if x >= 0 else '#ff4444' for x in df['unrealizedPnl']]
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df['symbol'],
        y=df['unrealizedPnl'],
        name='Unrealized P&L',
        marker_color=colors
    ))
    
    fig.update_layout(
        xaxis_title='Symbol',
        yaxis_title='P&L ($)',
        paper_bgcolor='#303030',
        plot_bgcolor='#2d2d2d',
        font_color='white',
        showlegend=False
    )
    fig.update_xaxes(gridcolor='#444')
    fig.update_yaxes(gridcolor='#444', zeroline=True, zerolinecolor='#666')
    
    return dcc.Graph(figure=fig, style={"height": "400px"})


@callback(
    Output("marketdata-table-container", "children"),
    Input("interval-component", "n_intervals")
)
def update_marketdata_table(n):
    df = state.get_market_data_df()
    
    if df.empty:
        return html.Div([
            html.P("No market data received yet.", style={"color": "#888"}),
            html.P("Make sure Finnhub is connected and you've subscribed to symbols.", 
                   style={"color": "#666", "fontSize": "12px"}),
            html.Code("curl -X POST http://localhost:8081/api/portfolio/market-data/subscribe "
                     "-H 'Content-Type: application/json' -d '{\"symbols\": [\"AAPL\", \"MSFT\"]}'",
                     style={"color": "#00d4aa", "fontSize": "11px"})
        ], style={"textAlign": "center", "padding": "50px"})
    
    columns_to_show = ['symbol', 'price', 'change', 'changePercent', 'open', 'high', 'low', 'previousClose', 'source']
    columns_to_show = [c for c in columns_to_show if c in df.columns]
    
    display_df = df[columns_to_show].copy()
    
    # Format columns
    for col in ['price', 'open', 'high', 'low', 'previousClose']:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(
                lambda x: f"${x:,.2f}" if pd.notnull(x) else "-"
            )
    
    if 'change' in display_df.columns:
        display_df['change'] = display_df['change'].apply(
            lambda x: f"{x:+,.2f}" if pd.notnull(x) else "-"
        )
    
    if 'changePercent' in display_df.columns:
        display_df['changePercent'] = display_df['changePercent'].apply(
            lambda x: f"{x:+,.2f}%" if pd.notnull(x) else "-"
        )
    
    col_names = {
        'symbol': 'Symbol',
        'price': 'Price',
        'change': 'Change',
        'changePercent': 'Change %',
        'open': 'Open',
        'high': 'High',
        'low': 'Low',
        'previousClose': 'Prev Close',
        'source': 'Source'
    }
    
    return dash_table.DataTable(
        data=display_df.to_dict('records'),
        columns=[{"name": col_names.get(col, col), "id": col} for col in columns_to_show],
        style_table={'overflowX': 'auto'},
        style_cell={
            'backgroundColor': '#2d2d2d',
            'color': 'white',
            'textAlign': 'right',
            'padding': '12px',
            'fontFamily': 'monospace'
        },
        style_header={
            'backgroundColor': '#1a1a1a',
            'color': '#00d4aa',
            'fontWeight': 'bold',
            'textAlign': 'center'
        },
        style_data_conditional=[
            {'if': {'column_id': 'symbol'}, 'textAlign': 'left', 'fontWeight': 'bold'}
        ]
    )


@callback(
    Output("subscribe-result", "children"),
    Input("subscribe-btn", "n_clicks"),
    State("subscribe-input", "value"),
    prevent_initial_call=True
)
def subscribe_symbols(n_clicks, symbols_str):
    if not symbols_str:
        return "Please enter symbols separated by commas"
    
    symbols = [s.strip().upper() for s in symbols_str.split(",") if s.strip()]
    
    if not symbols:
        return "No valid symbols entered"
    
    try:
        resp = requests.post(
            f"{FIX_CLIENT_URL}/api/portfolio/market-data/subscribe",
            json={"symbols": symbols},
            timeout=5
        )
        if resp.ok:
            result = resp.json()
            return f"✓ Subscribed to: {', '.join(symbols)}"
        else:
            return f"✗ Error: {resp.status_code} - {resp.text}"
    except Exception as e:
        return f"✗ Failed to subscribe: {e}"


@callback(
    Output("update-log-container", "children"),
    Input("interval-component", "n_intervals")
)
def update_debug_log(n):
    logs = state.get_update_log()
    if not logs:
        return html.P("No updates yet", style={"color": "#666"})
    
    return html.Div([
        html.Div(log, style={"color": "#aaa", "marginBottom": "5px"}) 
        for log in logs
    ])


if __name__ == '__main__':
    print("=" * 60)
    print("Portfolio Blotter Dashboard")
    print("=" * 60)
    print(f"FIX Client URL: {FIX_CLIENT_URL}")
    print(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    print(f"Subscribed channels: {list(REDIS_CHANNELS.values())}")
    print(f"Dashboard: http://localhost:{DASH_PORT}")
    print("=" * 60)
    app.run(debug=DASH_DEBUG, host=DASH_HOST, port=DASH_PORT)
