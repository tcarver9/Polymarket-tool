# dashboard.py
# Polymarket Trader Intelligence Dashboard
# Run with: streamlit run dashboard.py

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text

from config import DATABASE_URL, TRACKED_USERS

# Page configuration
st.set_page_config(
    page_title="Polymarket Intelligence",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 10px;
        padding: 20px;
        border: 1px solid #0f3460;
    }
    .profit { color: #00d26a; font-weight: bold; }
    .loss { color: #ff6b6b; font-weight: bold; }
    .win-badge {
        background-color: #00d26a;
        color: white;
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: bold;
    }
    .loss-badge {
        background-color: #ff6b6b;
        color: white;
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: bold;
    }
    .pending-badge {
        background-color: #ffa500;
        color: white;
        padding: 2px 8px;
        border-radius: 4px;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #1a1a2e;
        border-radius: 8px;
        padding: 10px 20px;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_database_engine():
    """Create cached database connection"""
    return create_engine(DATABASE_URL)


@st.cache_data(ttl=60)
def load_positions_from_api(wallet_address: str):
    """Load positions directly from Data API with actual P&L and resolution status"""
    import requests
    
    try:
        url = "https://data-api.polymarket.com/positions"
        response = requests.get(url, params={"user": wallet_address}, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, list):
            return pd.DataFrame(data)
        return pd.DataFrame()
    except Exception as e:
        st.warning(f"Could not fetch live positions: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_trader_data(user_id: str):
    """Load all data for a specific trader"""
    engine = get_database_engine()
    
    # Get fills with market resolution data
    fills_query = text("""
        SELECT 
            f.fill_id,
            f.fill_timestamp,
            f.side,
            f.size,
            f.price,
            f.total_value,
            f.total_fees,
            f.outcome as bet_choice,
            f.asset_id,
            m.question as market,
            m.category,
            m.resolved as market_resolved,
            m.resolution_outcome as market_result
        FROM fills f
        JOIN users u ON f.user_id = u.id
        LEFT JOIN markets m ON f.market_id = m.id
        WHERE u.user_id = :user_id
        ORDER BY f.fill_timestamp DESC
    """)
    
    fills_df = pd.read_sql(fills_query, engine, params={"user_id": user_id})
    
    # Get positions
    positions_query = text("""
        SELECT 
            p.asset_id,
            p.outcome,
            p.total_size,
            p.average_entry_price,
            p.total_cost_basis,
            p.unrealized_pnl,
            p.unrealized_pnl_pct,
            p.realized_pnl,
            p.is_closed,
            p.first_entry_timestamp,
            p.last_update_timestamp,
            m.question as market,
            m.category
        FROM positions p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN markets m ON p.market_id = m.id
        WHERE u.user_id = :user_id
        ORDER BY p.last_update_timestamp DESC
    """)
    
    positions_df = pd.read_sql(positions_query, engine, params={"user_id": user_id})
    
    # Get lot closures for detailed P&L with market resolution
    closures_query = text("""
        SELECT 
            lc.exit_timestamp,
            lc.size_closed,
            lc.exit_price,
            lc.gross_pnl,
            lc.net_pnl,
            lc.pnl_percentage,
            lc.holding_period_seconds,
            l.entry_price,
            l.asset_id,
            l.outcome as bet_choice,
            l.entry_timestamp,
            l.entry_fees,
            lc.exit_fees,
            m.question as market,
            m.resolved as market_resolved,
            m.resolution_outcome as market_result,
            m.resolution_timestamp
        FROM lot_closures lc
        JOIN lots l ON lc.lot_id = l.id
        JOIN users u ON l.user_id = u.id
        LEFT JOIN markets m ON l.asset_id = m.condition_id
        WHERE u.user_id = :user_id
        ORDER BY lc.exit_timestamp DESC
    """)
    
    closures_df = pd.read_sql(closures_query, engine, params={"user_id": user_id})
    
    # Get trade results - combines buy cost with sell P&L
    trade_results_query = text("""
        SELECT 
            f.fill_id,
            f.fill_timestamp,
            f.side,
            f.size,
            f.price,
            f.total_value as cost,
            f.total_fees,
            f.outcome,
            f.asset_id,
            m.question as market,
            CASE 
                WHEN f.side = 'BUY' THEN f.total_value + f.total_fees
                ELSE NULL
            END as trade_cost,
            CASE 
                WHEN f.side = 'SELL' THEN f.total_value - f.total_fees
                ELSE NULL
            END as trade_proceeds
        FROM fills f
        JOIN users u ON f.user_id = u.id
        LEFT JOIN markets m ON f.market_id = m.id
        WHERE u.user_id = :user_id
        ORDER BY f.fill_timestamp DESC
    """)
    
    trade_results_df = pd.read_sql(trade_results_query, engine, params={"user_id": user_id})
    
    return fills_df, positions_df, closures_df, trade_results_df


@st.cache_data(ttl=60)
def load_all_traders_summary():
    """Load summary statistics for all traders"""
    engine = get_database_engine()
    
    summary_query = text("""
        SELECT 
            u.user_id,
            COUNT(DISTINCT f.id) as total_trades,
            COALESCE(SUM(f.total_value), 0) as total_volume,
            COALESCE(SUM(CASE WHEN f.side = 'BUY' THEN f.total_value ELSE 0 END), 0) as buy_volume,
            COALESCE(SUM(CASE WHEN f.side = 'SELL' THEN f.total_value ELSE 0 END), 0) as sell_volume,
            MIN(f.fill_timestamp) as first_trade,
            MAX(f.fill_timestamp) as last_trade
        FROM users u
        LEFT JOIN fills f ON u.id = f.user_id
        GROUP BY u.user_id
        ORDER BY total_volume DESC
    """)
    
    return pd.read_sql(summary_query, engine)


def format_currency(value, include_sign=False):
    """Format value as currency"""
    if pd.isna(value):
        return "$0.00"
    if include_sign:
        return f"${value:+,.2f}"
    return f"${value:,.2f}"


def format_percentage(value, include_sign=False):
    """Format value as percentage"""
    if pd.isna(value):
        return "0.0%"
    if include_sign:
        return f"{value:+.1f}%"
    return f"{value:.1f}%"


def render_trader_metrics(fills_df, positions_df, closures_df):
    """Render key metrics for a trader"""
    col1, col2, col3, col4, col5 = st.columns(5)
    
    total_trades = len(fills_df)
    total_volume = fills_df['total_value'].sum() if not fills_df.empty else 0
    
    # Calculate P&L
    realized_pnl = positions_df['realized_pnl'].sum() if not positions_df.empty else 0
    unrealized_pnl = positions_df[positions_df['is_closed'] == False]['unrealized_pnl'].sum() if not positions_df.empty else 0
    total_pnl = realized_pnl + unrealized_pnl
    
    # Calculate win rate from closures
    if not closures_df.empty:
        wins = (closures_df['net_pnl'] > 0).sum()
        total_closed = len(closures_df)
        win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
    else:
        win_rate = 0
    
    # Open positions count
    open_positions = len(positions_df[positions_df['is_closed'] == False]) if not positions_df.empty else 0
    
    with col1:
        st.metric("Total Trades", f"{total_trades:,}")
    
    with col2:
        st.metric("Total Volume", format_currency(total_volume))
    
    with col3:
        delta_color = "normal" if realized_pnl >= 0 else "inverse"
        st.metric("Realized P&L", format_currency(realized_pnl, True), delta_color=delta_color)
    
    with col4:
        st.metric("Win Rate", format_percentage(win_rate))
    
    with col5:
        st.metric("Open Positions", open_positions)


def render_pnl_chart(closures_df, fills_df):
    """Render cumulative P&L chart"""
    if closures_df.empty:
        st.info("No closed positions yet - P&L chart will appear after trades are closed")
        return
    
    # Create cumulative P&L
    closures_df = closures_df.copy()
    closures_df['exit_timestamp'] = pd.to_datetime(closures_df['exit_timestamp'])
    closures_df = closures_df.sort_values('exit_timestamp')
    closures_df['cumulative_pnl'] = closures_df['net_pnl'].cumsum()
    
    fig = go.Figure()
    
    # Add cumulative P&L line
    fig.add_trace(go.Scatter(
        x=closures_df['exit_timestamp'],
        y=closures_df['cumulative_pnl'],
        mode='lines+markers',
        name='Cumulative P&L',
        line=dict(color='#00d26a', width=2),
        fill='tonexty',
        fillcolor='rgba(0, 210, 106, 0.1)'
    ))
    
    # Add zero line
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    
    fig.update_layout(
        title="Cumulative Realized P&L",
        xaxis_title="Date",
        yaxis_title="P&L ($)",
        template="plotly_dark",
        height=400,
        showlegend=False
    )
    
    st.plotly_chart(fig, use_container_width=True)


def render_trade_distribution(fills_df):
    """Render trade distribution charts"""
    if fills_df.empty:
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Buy vs Sell distribution
        side_counts = fills_df['side'].value_counts()
        fig = px.pie(
            values=side_counts.values,
            names=side_counts.index,
            title="Trade Direction",
            color_discrete_map={'BUY': '#00d26a', 'SELL': '#ff6b6b'},
            hole=0.4
        )
        fig.update_layout(template="plotly_dark", height=300)
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # Trade size distribution
        fig = px.histogram(
            fills_df,
            x='total_value',
            nbins=20,
            title="Trade Size Distribution",
            color_discrete_sequence=['#6366f1']
        )
        fig.update_layout(
            template="plotly_dark",
            height=300,
            xaxis_title="Trade Value ($)",
            yaxis_title="Count"
        )
        st.plotly_chart(fig, use_container_width=True)


def render_trade_history(fills_df):
    """Render trade history table with bet choices and market results"""
    if fills_df.empty:
        st.info("No trades found for this trader")
        return
    
    st.markdown("*All buy and sell orders. 🟣 BUY = opening a position, 🟠 SELL = closing a position*")
    
    # Prepare display dataframe
    display_df = fills_df.copy()
    display_df['fill_timestamp'] = pd.to_datetime(display_df['fill_timestamp'])
    
    # Format columns for display
    display_df['Time'] = display_df['fill_timestamp'].dt.strftime('%Y-%m-%d %H:%M')
    display_df['Market'] = display_df['market'].fillna('Unknown').apply(
        lambda x: str(x)[:50] + '...' if len(str(x)) > 50 else str(x)
    )
    
    # Bet choice column
    display_df['Bet Choice'] = display_df['bet_choice'].fillna('Unknown')
    
    # Market result
    def format_result(row):
        if pd.notna(row.get('market_resolved')) and row['market_resolved']:
            result = row.get('market_result', 'Unknown')
            return f"✅ {result}" if result else "✅ Resolved"
        return "⏳ Pending"
    
    display_df['Market Result'] = display_df.apply(format_result, axis=1)
    
    # Action with emoji
    display_df['Action'] = display_df['side'].apply(
        lambda x: '🟣 BUY' if x == 'BUY' else '🟠 SELL'
    )
    
    display_df['Size'] = display_df['size'].apply(lambda x: f"{x:,.2f}")
    display_df['Price'] = display_df['price'].apply(lambda x: f"${x:.4f}")
    display_df['Value'] = display_df['total_value'].apply(lambda x: f"${x:,.2f}")
    display_df['Fees'] = display_df['total_fees'].apply(lambda x: f"${x:.2f}")
    
    # Display using Streamlit dataframe
    st.dataframe(
        display_df[['Time', 'Market', 'Bet Choice', 'Market Result', 'Action', 'Size', 'Price', 'Value', 'Fees']].head(100),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Time": st.column_config.TextColumn("Time"),
            "Market": st.column_config.TextColumn("Market", width="large"),
            "Bet Choice": st.column_config.TextColumn("Bet Choice", help="What the trader bet on"),
            "Market Result": st.column_config.TextColumn("Result", help="Actual outcome of the market"),
            "Action": st.column_config.TextColumn("Action"),
            "Size": st.column_config.TextColumn("Size"),
            "Price": st.column_config.TextColumn("Price"),
            "Value": st.column_config.TextColumn("Value"),
            "Fees": st.column_config.TextColumn("Fees"),
        }
    )


def render_closed_trades_with_pnl(closures_df):
    """Render closed trades with clear profit/loss indicators and market results"""
    st.subheader("💰 Closed Trade Results")
    
    if closures_df.empty:
        st.info("No closed trades yet. P&L will appear when positions are sold.")
        return
    
    # Summary metrics
    total_wins = (closures_df['net_pnl'] > 0).sum()
    total_losses = (closures_df['net_pnl'] <= 0).sum()
    total_pnl = closures_df['net_pnl'].sum()
    avg_win = closures_df[closures_df['net_pnl'] > 0]['net_pnl'].mean() if total_wins > 0 else 0
    avg_loss = closures_df[closures_df['net_pnl'] <= 0]['net_pnl'].mean() if total_losses > 0 else 0
    
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Closed", len(closures_df))
    col2.metric("🟢 Wins", total_wins)
    col3.metric("🔴 Losses", total_losses)
    col4.metric("Avg Win", f"${avg_win:+,.2f}" if avg_win else "$0")
    col5.metric("Avg Loss", f"${avg_loss:+,.2f}" if avg_loss else "$0")
    
    st.markdown("---")
    
    # Prepare display dataframe
    display_df = closures_df.copy()
    display_df['exit_timestamp'] = pd.to_datetime(display_df['exit_timestamp'])
    display_df['entry_timestamp'] = pd.to_datetime(display_df['entry_timestamp'])
    
    # Calculate holding time in hours
    display_df['holding_hours'] = display_df['holding_period_seconds'] / 3600
    
    # Determine if trade was a win based on P&L
    display_df['is_win'] = display_df['net_pnl'] > 0
    display_df['is_loss'] = display_df['net_pnl'] < 0
    
    # Format for display
    display_df['Date'] = display_df['exit_timestamp'].dt.strftime('%Y-%m-%d %H:%M')
    display_df['Market'] = display_df['market'].fillna('Unknown').apply(
        lambda x: str(x)[:55] + '...' if len(str(x)) > 55 else str(x)
    )
    
    # Bet choice - what the trader bet on
    display_df['Bet'] = display_df['bet_choice'].fillna('Unknown')
    
    # Market result - what actually happened
    def format_market_result(row):
        if pd.notna(row.get('market_resolved')) and row['market_resolved']:
            result = row.get('market_result', 'Unknown')
            return f"✓ {result}" if result else "✓ Resolved"
        return "⏳ Pending"
    
    display_df['Result'] = display_df.apply(format_market_result, axis=1)
    
    display_df['Size'] = display_df['size_closed'].apply(lambda x: f"{x:,.2f}")
    display_df['Entry'] = display_df['entry_price'].apply(lambda x: f"${x:.3f}")
    display_df['Exit'] = display_df['exit_price'].apply(lambda x: f"${x:.3f}")
    display_df['Cost'] = display_df.apply(
        lambda row: f"${row['entry_price'] * row['size_closed']:,.2f}", axis=1
    )
    display_df['Proceeds'] = display_df.apply(
        lambda row: f"${row['exit_price'] * row['size_closed']:,.2f}", axis=1
    )
    
    # P&L column
    display_df['P&L'] = display_df.apply(
        lambda row: f"${row['net_pnl']:+,.2f} ({row['pnl_percentage']:+.1f}%)", axis=1
    )
    
    # Create display with clear win/loss indicators
    st.markdown("### Trade Details")
    st.markdown("*🟢 WIN = Profitable trade | 🔴 LOSS = Losing trade*")
    
    # Format P&L with emoji indicators
    def format_pnl_display(row):
        pnl = row['net_pnl']
        pct = row['pnl_percentage']
        if pnl > 0:
            return f"🟢 +${pnl:,.2f} ({pct:+.1f}%)"
        elif pnl < 0:
            return f"🔴 ${pnl:,.2f} ({pct:.1f}%)"
        else:
            return f"⚪ $0.00 (0%)"
    
    display_df['P&L'] = display_df.apply(format_pnl_display, axis=1)
    
    # Status column with clear indicator
    display_df['Status'] = display_df['net_pnl'].apply(
        lambda x: '✅ WIN' if x > 0 else ('❌ LOSS' if x < 0 else '➖ EVEN')
    )
    
    # Display using Streamlit dataframe with highlighting
    st.dataframe(
        display_df[['Date', 'Market', 'Bet', 'Result', 'Size', 'Cost', 'Proceeds', 'P&L', 'Status']].head(100),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Date": st.column_config.TextColumn("Date"),
            "Market": st.column_config.TextColumn("Market", width="large"),
            "Bet": st.column_config.TextColumn("Bet Choice", help="What the trader bet on (e.g., Over/Under)"),
            "Result": st.column_config.TextColumn("Market Result", help="Actual outcome of the event"),
            "Size": st.column_config.TextColumn("Size"),
            "Cost": st.column_config.TextColumn("Cost", help="Amount spent to open position"),
            "Proceeds": st.column_config.TextColumn("Proceeds", help="Amount received when closing"),
            "P&L": st.column_config.TextColumn("P&L", help="Net profit or loss"),
            "Status": st.column_config.TextColumn("Status"),
        }
    )
    
    # Download option
    with st.expander("📥 Download as CSV"):
        csv_df = display_df[['Date', 'Market', 'Bet', 'Result', 'Size', 'Cost', 'Proceeds', 'P&L', 'Status']].copy()
        csv_df.columns = ['Date', 'Market', 'Bet Choice', 'Market Result', 'Size', 'Cost', 'Proceeds', 'P&L', 'Status']
        st.download_button(
            "Download Trade Results",
            csv_df.to_csv(index=False),
            "trade_results.csv",
            "text/csv"
        )


def render_live_positions(wallet_address: str):
    """Render live positions from Data API with actual P&L and market outcomes"""
    st.subheader("📊 Live Positions & Results (from Polymarket API)")
    
    positions_df = load_positions_from_api(wallet_address)
    
    if positions_df.empty:
        st.info("No position data available from API")
        return
    
    # Summary stats
    total_positions = len(positions_df)
    resolved_positions = positions_df[positions_df['redeemable'] == True] if 'redeemable' in positions_df.columns else pd.DataFrame()
    open_positions = positions_df[positions_df['redeemable'] == False] if 'redeemable' in positions_df.columns else positions_df
    
    total_pnl = positions_df['cashPnl'].sum() if 'cashPnl' in positions_df.columns else 0
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Positions", total_positions)
    col2.metric("Resolved", len(resolved_positions))
    col3.metric("Open", len(open_positions))
    col4.metric("Total P&L", f"${total_pnl:+,.2f}")
    
    st.markdown("---")
    
    # Display resolved positions with actual outcomes
    if not resolved_positions.empty:
        st.markdown("### ✅ Resolved Markets (Final Results)")
        st.markdown("*These markets have ended - showing actual profit/loss*")
        
        display_df = resolved_positions.copy()
        
        # Determine if won or lost based on curPrice
        def get_result(row):
            cur_price = row.get('curPrice', 0)
            pnl = row.get('cashPnl', 0)
            if cur_price >= 0.99:  # Won
                return "🟢 WON"
            elif cur_price <= 0.01:  # Lost
                return "🔴 LOST"
            else:
                return "⚪ PARTIAL"
        
        display_df['Result'] = display_df.apply(get_result, axis=1)
        display_df['Market'] = display_df['title'].fillna('Unknown').apply(
            lambda x: str(x)[:50] + '...' if len(str(x)) > 50 else str(x)
        )
        display_df['Bet'] = display_df['outcome'].fillna('Unknown')
        display_df['Size'] = display_df['size'].apply(lambda x: f"{x:,.2f}")
        display_df['Avg Price'] = display_df['avgPrice'].apply(lambda x: f"${x:.4f}")
        display_df['Cost'] = display_df['initialValue'].apply(lambda x: f"${x:,.2f}")
        
        # P&L with color
        def format_pnl(row):
            pnl = row['cashPnl']
            pct = row.get('percentPnl', 0)
            if pnl > 0:
                return f"🟢 +${pnl:,.2f} ({pct:+.1f}%)"
            elif pnl < 0:
                return f"🔴 ${pnl:,.2f} ({pct:.1f}%)"
            else:
                return f"⚪ $0.00"
        
        display_df['P&L'] = display_df.apply(format_pnl, axis=1)
        
        st.dataframe(
            display_df[['Market', 'Bet', 'Size', 'Avg Price', 'Cost', 'P&L', 'Result']],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Market": st.column_config.TextColumn("Market", width="large"),
                "Bet": st.column_config.TextColumn("Bet Choice", help="What they bet on"),
                "P&L": st.column_config.TextColumn("Profit/Loss"),
                "Result": st.column_config.TextColumn("Outcome"),
            }
        )
        
        # Summary of resolved positions
        wins = (resolved_positions['curPrice'] >= 0.99).sum() if 'curPrice' in resolved_positions.columns else 0
        losses = (resolved_positions['curPrice'] <= 0.01).sum() if 'curPrice' in resolved_positions.columns else 0
        
        st.markdown(f"**Resolved Summary:** {wins} wins, {losses} losses")
    
    # Display open positions
    if not open_positions.empty:
        st.markdown("### ⏳ Open Positions (Pending)")
        st.markdown("*These markets haven't resolved yet*")
        
        display_df = open_positions.copy()
        display_df['Market'] = display_df['title'].fillna('Unknown').apply(
            lambda x: str(x)[:50] + '...' if len(str(x)) > 50 else str(x)
        )
        display_df['Bet'] = display_df['outcome'].fillna('Unknown')
        display_df['Size'] = display_df['size'].apply(lambda x: f"{x:,.2f}")
        display_df['Avg Price'] = display_df['avgPrice'].apply(lambda x: f"${x:.4f}")
        display_df['Current Price'] = display_df['curPrice'].apply(lambda x: f"${x:.4f}")
        display_df['Cost'] = display_df['initialValue'].apply(lambda x: f"${x:,.2f}")
        display_df['Current Value'] = display_df['currentValue'].apply(lambda x: f"${x:,.2f}")
        display_df['Unrealized P&L'] = display_df.apply(
            lambda row: f"${row['cashPnl']:+,.2f} ({row.get('percentPnl', 0):+.1f}%)" if 'cashPnl' in row else "$0",
            axis=1
        )
        
        st.dataframe(
            display_df[['Market', 'Bet', 'Size', 'Avg Price', 'Current Price', 'Cost', 'Current Value', 'Unrealized P&L']],
            use_container_width=True,
            hide_index=True
        )


def render_positions_table(positions_df):
    """Render open and closed positions with clear P&L indicators"""
    if positions_df.empty:
        st.info("No positions found")
        return
    
    # Split into open and closed
    open_positions = positions_df[positions_df['is_closed'] == False].copy()
    closed_positions = positions_df[positions_df['is_closed'] == True].copy()
    
    # Summary metrics
    if not open_positions.empty:
        total_exposure = open_positions['total_cost_basis'].sum()
        total_unrealized = open_positions['unrealized_pnl'].sum()
        st.metric("Total Open Exposure", f"${total_exposure:,.2f}", 
                  f"Unrealized: ${total_unrealized:+,.2f}")
    
    tab1, tab2 = st.tabs([f"🟡 Open Positions ({len(open_positions)})", f"✅ Closed Positions ({len(closed_positions)})"])
    
    with tab1:
        if open_positions.empty:
            st.info("No open positions - all trades have been closed")
        else:
            open_positions['Market'] = open_positions['market'].fillna('Unknown').apply(
                lambda x: str(x)[:45] + '...' if len(str(x)) > 45 else str(x)
            )
            open_positions['Size'] = open_positions['total_size'].apply(lambda x: f"{x:,.2f}")
            open_positions['Avg Entry'] = open_positions['average_entry_price'].apply(
                lambda x: f"${x:.4f}" if pd.notna(x) else "-"
            )
            open_positions['Cost Basis'] = open_positions['total_cost_basis'].apply(lambda x: f"${x:,.2f}")
            
            # Unrealized P&L with emoji indicators
            def format_unrealized(row):
                pnl = row['unrealized_pnl'] if pd.notna(row['unrealized_pnl']) else 0
                pct = row['unrealized_pnl_pct'] if pd.notna(row['unrealized_pnl_pct']) else 0
                if pnl > 0:
                    return f"🟢 ${pnl:+,.2f} ({pct:+.1f}%)"
                elif pnl < 0:
                    return f"🔴 ${pnl:+,.2f} ({pct:+.1f}%)"
                else:
                    return f"⚪ $0.00 (0%)"
            
            open_positions['Unrealized P&L'] = open_positions.apply(format_unrealized, axis=1)
            
            st.dataframe(
                open_positions[['Market', 'outcome', 'Size', 'Avg Entry', 'Cost Basis', 'Unrealized P&L']],
                use_container_width=True,
                hide_index=True
            )
    
    with tab2:
        if closed_positions.empty:
            st.info("No closed positions yet")
        else:
            closed_positions['Market'] = closed_positions['market'].fillna('Unknown').apply(
                lambda x: str(x)[:45] + '...' if len(str(x)) > 45 else str(x)
            )
            
            # Realized P&L with emoji indicators
            def format_realized(pnl):
                if pd.isna(pnl):
                    return "⚪ $0.00"
                if pnl > 0:
                    return f"🟢 ${pnl:+,.2f}"
                elif pnl < 0:
                    return f"🔴 ${pnl:+,.2f}"
                else:
                    return f"⚪ $0.00"
            
            closed_positions['Realized P&L'] = closed_positions['realized_pnl'].apply(format_realized)
            closed_positions['Result'] = closed_positions['realized_pnl'].apply(
                lambda x: '✅ WIN' if x > 0 else ('❌ LOSS' if x < 0 else '➖ EVEN')
            )
            
            st.dataframe(
                closed_positions[['Market', 'outcome', 'Realized P&L', 'Result']].head(50),
                use_container_width=True,
                hide_index=True
            )


def render_profitability_analysis(closures_df):
    """Render detailed profitability analysis"""
    if closures_df.empty:
        st.info("No closed trades for profitability analysis")
        return
    
    # Win/Loss Summary
    st.subheader("📊 Win/Loss Breakdown")
    
    wins = closures_df[closures_df['net_pnl'] > 0]
    losses = closures_df[closures_df['net_pnl'] <= 0]
    
    total_trades = len(closures_df)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
    
    total_profit = wins['net_pnl'].sum() if not wins.empty else 0
    total_loss = abs(losses['net_pnl'].sum()) if not losses.empty else 0
    net_pnl = total_profit - total_loss
    profit_factor = (total_profit / total_loss) if total_loss > 0 else float('inf')
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Win Rate", f"{win_rate:.1f}%", f"{win_count}/{total_trades} trades")
    col2.metric("Total Profit", f"${total_profit:,.2f}", f"from {win_count} wins")
    col3.metric("Total Loss", f"-${total_loss:,.2f}", f"from {loss_count} losses")
    col4.metric("Net P&L", f"${net_pnl:+,.2f}", 
                f"Profit Factor: {profit_factor:.2f}x" if profit_factor != float('inf') else "∞")
    
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Win/Loss pie chart
        fig = go.Figure(data=[go.Pie(
            labels=['🟢 Wins', '🔴 Losses'],
            values=[win_count, loss_count],
            hole=0.4,
            marker_colors=['#00d26a', '#ff6b6b']
        )])
        fig.update_layout(
            title="Win/Loss Ratio",
            template="plotly_dark",
            height=300
        )
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        # P&L distribution
        fig = px.histogram(
            closures_df,
            x='net_pnl',
            nbins=30,
            title="P&L Distribution per Trade",
            color=closures_df['net_pnl'].apply(lambda x: 'Win' if x > 0 else 'Loss'),
            color_discrete_map={'Win': '#00d26a', 'Loss': '#ff6b6b'}
        )
        fig.add_vline(x=0, line_dash="dash", line_color="white", opacity=0.5)
        fig.update_layout(
            template="plotly_dark",
            height=300,
            xaxis_title="Net P&L ($)",
            yaxis_title="Count",
            showlegend=False
        )
        st.plotly_chart(fig, use_container_width=True)
    
    # Average metrics
    st.subheader("📈 Performance Metrics")
    
    avg_win = wins['net_pnl'].mean() if not wins.empty else 0
    avg_loss = losses['net_pnl'].mean() if not losses.empty else 0
    avg_win_pct = wins['pnl_percentage'].mean() if not wins.empty else 0
    avg_loss_pct = losses['pnl_percentage'].mean() if not losses.empty else 0
    largest_win = wins['net_pnl'].max() if not wins.empty else 0
    largest_loss = losses['net_pnl'].min() if not losses.empty else 0
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**Average Trade**")
        st.metric("Avg Win", f"${avg_win:,.2f}", f"{avg_win_pct:+.1f}%")
        st.metric("Avg Loss", f"${avg_loss:,.2f}", f"{avg_loss_pct:+.1f}%")
    
    with col2:
        st.markdown("**Extremes**")
        st.metric("Largest Win", f"${largest_win:,.2f}")
        st.metric("Largest Loss", f"${largest_loss:,.2f}")
    
    with col3:
        st.markdown("**Risk/Reward**")
        risk_reward = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
        expectancy = (win_rate/100 * avg_win) + ((100-win_rate)/100 * avg_loss)
        st.metric("Risk/Reward", f"{risk_reward:.2f}:1" if risk_reward != float('inf') else "∞")
        st.metric("Expectancy", f"${expectancy:,.2f}/trade")
    
    # Holding period analysis
    if 'holding_period_seconds' in closures_df.columns:
        closures_df = closures_df.copy()
        closures_df['holding_hours'] = closures_df['holding_period_seconds'] / 3600
        
        st.markdown("---")
        st.subheader("⏱️ Holding Period Analysis")
        
        col1, col2, col3, col4 = st.columns(4)
        
        avg_hold = closures_df['holding_hours'].mean()
        avg_hold_wins = wins['holding_period_seconds'].mean() / 3600 if not wins.empty else 0
        avg_hold_losses = losses['holding_period_seconds'].mean() / 3600 if not losses.empty else 0
        
        def format_time(hours):
            if hours < 1:
                return f"{hours*60:.0f} min"
            elif hours < 24:
                return f"{hours:.1f} hours"
            else:
                return f"{hours/24:.1f} days"
        
        col1.metric("Avg Hold Time", format_time(avg_hold))
        col2.metric("Avg Win Hold", format_time(avg_hold_wins))
        col3.metric("Avg Loss Hold", format_time(avg_hold_losses))
        col4.metric("Shortest/Longest", 
                   f"{format_time(closures_df['holding_hours'].min())} / {format_time(closures_df['holding_hours'].max())}")


def render_overview_page():
    """Render the overview/leaderboard page"""
    st.header("🏆 Trader Leaderboard")
    
    summary_df = load_all_traders_summary()
    
    if summary_df.empty:
        st.info("No trader data available yet. Run main.py to start collecting data.")
        return
    
    # Filter out traders with no trades
    active_traders = summary_df[summary_df['total_trades'] > 0].copy()
    
    if active_traders.empty:
        st.info("No trades recorded yet.")
        return
    
    # Format for display
    active_traders['Volume'] = active_traders['total_volume'].apply(format_currency)
    active_traders['Trades'] = active_traders['total_trades']
    active_traders['First Trade'] = pd.to_datetime(active_traders['first_trade']).dt.strftime('%Y-%m-%d')
    active_traders['Last Trade'] = pd.to_datetime(active_traders['last_trade']).dt.strftime('%Y-%m-%d')
    
    st.dataframe(
        active_traders[['user_id', 'Trades', 'Volume', 'First Trade', 'Last Trade']],
        use_container_width=True,
        hide_index=True,
        column_config={
            "user_id": "Trader",
            "Trades": st.column_config.NumberColumn("Trades"),
            "Volume": "Total Volume",
        }
    )
    
    # Volume chart
    if len(active_traders) > 1:
        fig = px.bar(
            active_traders.head(10),
            x='user_id',
            y='total_volume',
            title="Top Traders by Volume",
            color='total_volume',
            color_continuous_scale='Viridis'
        )
        fig.update_layout(
            template="plotly_dark",
            xaxis_title="Trader",
            yaxis_title="Volume ($)",
            showlegend=False
        )
        st.plotly_chart(fig, use_container_width=True)


def main():
    """Main dashboard application"""
    
    # Sidebar
    st.sidebar.title("🎯 Polymarket Intelligence")
    st.sidebar.markdown("---")
    
    # Get active traders
    active_users = [u for u in TRACKED_USERS if u.user_id and u.primary_address]
    
    if not active_users:
        st.error("No traders configured in config.py")
        return
    
    # Navigation
    page_options = ["📊 Overview"] + [f"👤 {u.user_id}" for u in active_users]
    selected_page = st.sidebar.radio("Navigation", page_options)
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Data Refresh")
    if st.sidebar.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()
    
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"*Tracking {len(active_users)} traders*")
    
    # Main content
    if selected_page == "📊 Overview":
        render_overview_page()
    else:
        # Extract trader name from selection
        trader_name = selected_page.replace("👤 ", "")
        
        st.header(f"📈 {trader_name}")
        
        # Get wallet address for this trader
        trader_user = next((u for u in active_users if u.user_id == trader_name), None)
        wallet_address = trader_user.primary_address if trader_user else None
        
        # Load trader data
        with st.spinner("Loading trader data..."):
            fills_df, positions_df, closures_df, trade_results_df = load_trader_data(trader_name)
        
        if fills_df.empty and not wallet_address:
            st.info(f"No trade data found for {trader_name}. Data will appear once trades are ingested.")
            return
        
        # Render metrics
        render_trader_metrics(fills_df, positions_df, closures_df)
        
        st.markdown("---")
        
        # Tabs for different views
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "🎯 Live Results",
            "💰 Closed Trades",
            "📈 P&L Analysis",
            "📋 All Trades", 
            "💼 DB Positions",
            "🔍 Patterns"
        ])
        
        with tab1:
            if wallet_address:
                render_live_positions(wallet_address)
            else:
                st.warning("Wallet address not found for this trader")
        
        with tab2:
            render_closed_trades_with_pnl(closures_df)
        
        with tab3:
            render_pnl_chart(closures_df, fills_df)
            render_trade_distribution(fills_df)
        
        with tab4:
            st.subheader("All Trades (Buys & Sells)")
            render_trade_history(fills_df)
        
        with tab5:
            render_positions_table(positions_df)
        
        with tab6:
            render_profitability_analysis(closures_df)


if __name__ == "__main__":
    main()
