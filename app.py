"""
Portfolio Blotter - Real-time Position Monitoring Dashboard
Subscribes to Redis pub/sub channels for live updates from FIX Client
"""

import json
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

# Configuration
FIX_CLIENT_URL = "http://localhost:8081"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_CHANNELS = {
    "positions": "positions:updates",
    "executions": "executions:updates",
    "orders": "orders:updates"
}

# Global state for real-time data
class PortfolioState:
    def __init__(self):
        self.positions = {}
        self.executions = deque(maxlen=100)  # Keep last 100 executions
        self.orders = {}
        self.portfolio_summary = {}
        self.last_update = None
        self.connected = False
        self.lock = threading.Lock()
    
    def update_position(self, position_data: dict):
        with self.lock:
            symbol = position_data.get('symbol')
            if symbol:
                self.positions[symbol] = position_data
                self.last_update = datetime.now()
    
    def add_execution(self, exec_data: dict):
        with self.lock:
            self.executions.appendleft(exec_data)
            self.last_update = datetime.now()
    
    def update_order(self, order_data: dict):
        with self.lock:
            cl_ord_id = order_data.get('clOrdId')
            if cl_ord_id:
                self.orders[cl_ord_id] = order_data
                self.last_update = datetime.now()
    
    def get_positions_df(self) -> pd.DataFrame:
        with self.lock:
            if not self.positions:
                return pd.DataFrame()
            df = pd.DataFrame(list(self.positions.values()))
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

# Global state instance
state = PortfolioState()

# Redis subscriber thread
class RedisSubscriber(threading.Thread):
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
                decode_responses=True
            )
            self.redis_client.ping()
            self.pubsub = self.redis_client.pubsub()
            self.pubsub.subscribe(
                REDIS_CHANNELS["positions"],
                REDIS_CHANNELS["executions"],
                REDIS_CHANNELS["orders"]
            )
            self.state.connected = True
            print(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
            return True
        except Exception as e:
            print(f"Failed to connect to Redis: {e}")
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
            except Exception as e:
                print(f"Redis subscriber error: {e}")
                self.state.connected = False
                # Try to reconnect
                if not self.connect():
                    import time
                    time.sleep(5)
    
    def handle_message(self, channel: str, data: str):
        try:
            # Data from Redis pub/sub comes as a string - parse it
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            
            # The FIX client publishes JSON strings, so we need to parse
            payload = json.loads(data)
            
            # Handle case where payload is still a string (double-encoded)
            if isinstance(payload, str):
                payload = json.loads(payload)
            
            msg_type = payload.get('type', '') if isinstance(payload, dict) else ''
            msg_data = payload.get('data', {}) if isinstance(payload, dict) else {}
            
            if channel == REDIS_CHANNELS["positions"]:
                if msg_type == "POSITION_UPDATE":
                    self.state.update_position(msg_data)
                    print(f"Position update: {msg_data.get('symbol', 'unknown')}")
            
            elif channel == REDIS_CHANNELS["executions"]:
                if msg_type == "EXECUTION":
                    self.state.add_execution(msg_data)
                    print(f"Execution: {msg_data.get('execType', '')} {msg_data.get('symbol', '')}")
            
            elif channel == REDIS_CHANNELS["orders"]:
                if isinstance(msg_data, dict) and msg_data:
                    self.state.update_order(msg_data)
                    print(f"Order update: {msg_type} {msg_data.get('clOrdId', '')}")
                
        except json.JSONDecodeError as e:
            print(f"Failed to parse message: {e}, data: {data[:100] if data else 'empty'}")
        except Exception as e:
            print(f"Error handling message: {e}")
    
    def stop(self):
        self.running = False
        if self.pubsub:
            self.pubsub.close()
        if self.redis_client:
            self.redis_client.close()

# Start Redis subscriber
subscriber = RedisSubscriber(state)
subscriber.start()

# Fetch initial data from REST API
def fetch_initial_data():
    """Fetch current portfolio state from FIX Client REST API"""
    try:
        # Fetch portfolio summary
        resp = requests.get(f"{FIX_CLIENT_URL}/api/portfolio/summary", timeout=5)
        if resp.ok:
            summary = resp.json()
            state.portfolio_summary = summary
            for pos in summary.get('positions', []):
                state.update_position(pos)
        
        # Fetch recent executions
        resp = requests.get(f"{FIX_CLIENT_URL}/api/executions?limit=50", timeout=5)
        if resp.ok:
            for exec_data in resp.json():
                state.add_execution(exec_data)
        
        # Fetch orders
        resp = requests.get(f"{FIX_CLIENT_URL}/api/orders", timeout=5)
        if resp.ok:
            for order in resp.json():
                state.update_order(order)
                
        print("Initial data loaded from FIX Client")
    except Exception as e:
        print(f"Failed to fetch initial data: {e}")

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

HEADER_STYLE = {
    "color": "#00d4aa",
    "marginBottom": "10px"
}

# Layout
app.layout = dbc.Container([
    # Header
    dbc.Row([
        dbc.Col([
            html.H1("📊 Portfolio Blotter", style={"color": "#00d4aa"}),
            html.P("Real-time position monitoring from FIX Client", 
                   style={"color": "#888"})
        ], width=8),
        dbc.Col([
            html.Div(id="connection-status", style={"textAlign": "right"}),
            html.Div(id="last-update", style={"textAlign": "right", "color": "#888"})
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
        # Positions Tab
        dbc.Tab([
            dbc.Row([
                dbc.Col([
                    html.Div(id="positions-table-container", style={"marginTop": "20px"})
                ], width=8),
                dbc.Col([
                    html.Div(id="position-chart-container", style={"marginTop": "20px"})
                ], width=4)
            ])
        ], label="Positions", tab_id="tab-positions"),
        
        # Executions Tab
        dbc.Tab([
            html.Div(id="executions-table-container", style={"marginTop": "20px"})
        ], label="Executions", tab_id="tab-executions"),
        
        # Orders Tab
        dbc.Tab([
            html.Div(id="orders-table-container", style={"marginTop": "20px"})
        ], label="Orders", tab_id="tab-orders"),
        
        # P&L Chart Tab
        dbc.Tab([
            html.Div(id="pnl-chart-container", style={"marginTop": "20px"})
        ], label="P&L Analysis", tab_id="tab-pnl")
    ], id="tabs", active_tab="tab-positions"),
    
    # Auto-refresh interval
    dcc.Interval(
        id='interval-component',
        interval=1000,  # 1 second refresh
        n_intervals=0
    ),
    
    # Store for client-side data
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
        conn_status = dbc.Badge("● Connected", color="success", className="me-1")
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
        return html.Div("No positions", style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    # Filter open positions
    df = df[df['quantity'] != 0].copy()
    
    if df.empty:
        return html.Div("No open positions", style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    # Format columns
    columns_to_show = ['symbol', 'quantity', 'avgCost', 'currentPrice', 'marketValue', 'unrealizedPnl', 'realizedPnl']
    columns_to_show = [c for c in columns_to_show if c in df.columns]
    
    # Create display dataframe
    display_df = df[columns_to_show].copy()
    
    # Format numeric columns
    for col in ['avgCost', 'currentPrice', 'marketValue', 'unrealizedPnl', 'realizedPnl']:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(lambda x: f"${x:,.2f}" if pd.notnull(x) else "-")
    
    return dash_table.DataTable(
        data=display_df.to_dict('records'),
        columns=[{"name": col.replace('Pnl', ' P&L').replace('avg', 'Avg ').replace('current', 'Current ').replace('market', 'Market ').title(), 
                  "id": col} for col in columns_to_show],
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
            {
                'if': {'column_id': 'symbol'},
                'textAlign': 'left',
                'fontWeight': 'bold'
            },
            {
                'if': {'column_id': 'quantity'},
                'textAlign': 'center'
            }
        ]
    )


@callback(
    Output("position-chart-container", "children"),
    Input("interval-component", "n_intervals")
)
def update_position_chart(n):
    df = state.get_positions_df()
    
    if df.empty or 'marketValue' not in df.columns:
        return html.Div("No data for chart", style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    # Filter open positions
    df = df[df['quantity'] != 0].copy()
    
    if df.empty:
        return html.Div("No open positions for chart", style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    # Create pie chart of market value distribution
    fig = px.pie(
        df, 
        values='marketValue', 
        names='symbol',
        title='Position Distribution by Market Value',
        color_discrete_sequence=px.colors.qualitative.Set3
    )
    
    fig.update_layout(
        paper_bgcolor='#303030',
        plot_bgcolor='#303030',
        font_color='white',
        title_font_color='#00d4aa'
    )
    
    return dcc.Graph(figure=fig, style={"height": "400px"})


@callback(
    Output("executions-table-container", "children"),
    Input("interval-component", "n_intervals")
)
def update_executions_table(n):
    df = state.get_executions_df()
    
    if df.empty:
        return html.Div("No executions", style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    columns_to_show = ['timestamp', 'symbol', 'side', 'execType', 'lastQuantity', 'lastPrice', 'cumQuantity', 'orderStatus']
    columns_to_show = [c for c in columns_to_show if c in df.columns]
    
    display_df = df[columns_to_show].copy()
    
    # Format price columns
    for col in ['lastPrice', 'avgPrice']:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(lambda x: f"${x:,.2f}" if pd.notnull(x) and x != 0 else "-")
    
    return dash_table.DataTable(
        data=display_df.head(50).to_dict('records'),
        columns=[{"name": col.replace('last', 'Last ').replace('cum', 'Cum ').replace('exec', 'Exec ').replace('order', 'Order ').title(), 
                  "id": col} for col in columns_to_show],
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
            {
                'if': {'filter_query': '{side} = "BUY"', 'column_id': 'side'},
                'color': '#00ff88'
            },
            {
                'if': {'filter_query': '{side} = "SELL"', 'column_id': 'side'},
                'color': '#ff4444'
            },
            {
                'if': {'filter_query': '{execType} = "FILL"', 'column_id': 'execType'},
                'color': '#00d4aa',
                'fontWeight': 'bold'
            }
        ]
    )


@callback(
    Output("orders-table-container", "children"),
    Input("interval-component", "n_intervals")
)
def update_orders_table(n):
    df = state.get_orders_df()
    
    if df.empty:
        return html.Div("No orders", style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    columns_to_show = ['clOrdId', 'symbol', 'side', 'orderType', 'quantity', 'price', 'status', 'filledQuantity', 'leavesQuantity']
    columns_to_show = [c for c in columns_to_show if c in df.columns]
    
    display_df = df[columns_to_show].copy()
    
    # Format price
    if 'price' in display_df.columns:
        display_df['price'] = display_df['price'].apply(lambda x: f"${x:,.2f}" if pd.notnull(x) else "-")
    
    return dash_table.DataTable(
        data=display_df.to_dict('records'),
        columns=[{"name": col.replace('clOrdId', 'Order ID').replace('filled', 'Filled ').replace('leaves', 'Leaves ').replace('order', 'Order ').title(), 
                  "id": col} for col in columns_to_show],
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
            {
                'if': {'filter_query': '{side} = "BUY"', 'column_id': 'side'},
                'color': '#00ff88'
            },
            {
                'if': {'filter_query': '{side} = "SELL"', 'column_id': 'side'},
                'color': '#ff4444'
            },
            {
                'if': {'filter_query': '{status} = "FILLED"', 'column_id': 'status'},
                'color': '#00d4aa',
                'fontWeight': 'bold'
            },
            {
                'if': {'filter_query': '{status} = "CANCELLED"', 'column_id': 'status'},
                'color': '#888'
            },
            {
                'if': {'filter_query': '{status} = "REJECTED"', 'column_id': 'status'},
                'color': '#ff4444'
            }
        ]
    )


@callback(
    Output("pnl-chart-container", "children"),
    Input("interval-component", "n_intervals")
)
def update_pnl_chart(n):
    df = state.get_positions_df()
    
    if df.empty:
        return html.Div("No P&L data", style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    # Filter positions with P&L data
    df = df[df['quantity'] != 0].copy()
    
    if df.empty or 'unrealizedPnl' not in df.columns:
        return html.Div("No P&L data available", style={"color": "#888", "textAlign": "center", "padding": "50px"})
    
    # Create bar chart of P&L by symbol
    fig = go.Figure()
    
    # Unrealized P&L bars
    colors = ['#00ff88' if x >= 0 else '#ff4444' for x in df['unrealizedPnl']]
    
    fig.add_trace(go.Bar(
        x=df['symbol'],
        y=df['unrealizedPnl'],
        name='Unrealized P&L',
        marker_color=colors
    ))
    
    fig.update_layout(
        title='P&L by Position',
        xaxis_title='Symbol',
        yaxis_title='P&L ($)',
        paper_bgcolor='#303030',
        plot_bgcolor='#2d2d2d',
        font_color='white',
        title_font_color='#00d4aa',
        showlegend=True,
        legend=dict(
            bgcolor='#303030',
            bordercolor='#444'
        )
    )
    
    fig.update_xaxes(gridcolor='#444')
    fig.update_yaxes(gridcolor='#444', zeroline=True, zerolinecolor='#666')
    
    return dcc.Graph(figure=fig, style={"height": "500px"})


if __name__ == '__main__':
    print("Starting Portfolio Blotter Dashboard...")
    print(f"FIX Client URL: {FIX_CLIENT_URL}")
    print(f"Redis: {REDIS_HOST}:{REDIS_PORT}")
    print("Dashboard will be available at http://localhost:8060")
    app.run(debug=True, host='0.0.0.0', port=8060)