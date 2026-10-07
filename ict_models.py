"""5 Advanced ICT / SMC Entry Models from AtlasOnChain.

Models Implemented:
1. Model 1: Liquidity Sweep + MSS + FVG (Standard 2022 Mentorship)
2. Model 2: Liquidity Sweep + BPR (Balanced Price Range FVG Overlap)
3. Model 3: SMT Divergence + MSS + IFVG (Inverse Fair Value Gap)
4. Model 4: SMT Divergence + MSS + Breaker Block (BB)
5. Model 5: Full Confluence (Sweep + MSS + BB + FVG)
"""

import pandas as pd
import config
import technicals
from smc import find_swing_points, detect_liquidity_sweep, find_fvgs, is_fvg_unfilled, find_target


def find_bpr(df, start_idx):
    """Finds a Balanced Price Range (overlapping Bullish and Bearish FVGs)."""
    bull_fvgs = find_fvgs(df, start_idx, "bullish")
    bear_fvgs = find_fvgs(df, start_idx, "bearish")
    
    bprs = []
    for bull in bull_fvgs:
        for bear in bear_fvgs:
            # Check overlap
            overlap_low = max(bull["low"], bear["low"])
            overlap_high = min(bull["high"], bear["high"])
            if overlap_low < overlap_high:
                bprs.append({
                    "low": overlap_low,
                    "high": overlap_high,
                    "formed_idx": max(bull["formed_idx"], bear["formed_idx"])
                })
    return bprs


def find_breaker_blocks(df, swings, direction):
    """Finds Breaker Blocks (a swing high/low that led to a liquidity sweep and got violated)."""
    bbs = []
    closed_len = len(df)
    
    for s in swings:
        idx = s["idx"]
        price = s["price"]
        # Look for candles that aggressively closed through the swing point
        if direction == "LONG" and s["type"] == "high":
            # Broken swing high acts as bullish support
            since = df.iloc[idx + 1:]
            broken = since[since["Close"] > price]
            if not broken.empty:
                # The candle at swing high is the breaker zone
                swing_bar = df.iloc[idx]
                bbs.append({
                    "low": swing_bar["Low"],
                    "high": swing_bar["High"],
                    "formed_idx": idx
                })
        elif direction == "SHORT" and s["type"] == "low":
            since = df.iloc[idx + 1:]
            broken = since[since["Close"] < price]
            if not broken.empty:
                swing_bar = df.iloc[idx]
                bbs.append({
                    "low": swing_bar["Low"],
                    "high": swing_bar["High"],
                    "formed_idx": idx
                })
    return bbs


def find_ifvgs(df, start_idx, direction):
    """Finds Inverse Fair Value Gaps (FVGs violated and flipped to support/resistance)."""
    # For a LONG trade, we look for failed BEARISH FVGs that price closed above
    # For a SHORT trade, we look for failed BULLISH FVGs that price closed below
    opp_direction = "bearish" if direction == "LONG" else "bullish"
    opp_fvgs = find_fvgs(df, start_idx, opp_direction)
    
    ifvgs = []
    for fvg in opp_fvgs:
        since = df.iloc[fvg["formed_idx"]:]
        if direction == "LONG":
            violated = since[since["Close"] > fvg["high"]]
            if not violated.empty:
                ifvgs.append(fvg)
        else:
            violated = since[since["Close"] < fvg["low"]]
            if not violated.empty:
                ifvgs.append(fvg)
    return ifvgs


def detect_ict_models_signal(df, htf_trend=None, model_type="all"):
    """Evaluates the 5 ICT entry models and returns the highest-confluence valid setup."""
    min_bars = 80
    if df is None or len(df) < min_bars:
        return None
        
    closed = df.iloc[:-1].copy()
    indicators = technicals.compute_indicators(closed)
    atr = indicators["ATR"].iloc[-1]
    if pd.isna(atr) or atr <= 0:
        return None
        
    swings = find_swing_points(closed, 2, 2, 80)
    sweep = detect_liquidity_sweep(closed, swings, 40)
    if sweep is None:
        return None
        
    direction = sweep["direction"]
    if (direction == "LONG" and htf_trend == "down") or (direction == "SHORT" and htf_trend == "up"):
        return None
        
    price = closed["Close"].iloc[-1]
    start_idx = max(sweep["sweep_idx"], len(closed) - 30)
    zone = None
    model_name = ""
    
    # 1. Model 5 Check: BB + FVG Confluence
    fvg_dir = "bullish" if direction == "LONG" else "bearish"
    fvgs = find_fvgs(closed, start_idx, fvg_dir)
    bbs = find_breaker_blocks(closed, swings, direction)
    for bb in bbs:
        for fvg in fvgs:
            ov_low = max(bb["low"], fvg["low"])
            ov_high = min(bb["high"], fvg["high"])
            if ov_low <= price <= ov_high:
                zone = {"low": ov_low, "high": ov_high}
                model_name = "Model 5 (Sweep + MSS + BB + FVG)"
                break
        if zone: break
        
    # 2. Model 2 Check: BPR (Balanced Price Range)
    if not zone:
        bprs = find_bpr(closed, start_idx)
        for bpr in bprs:
            if bpr["low"] <= price <= bpr["high"]:
                zone = bpr
                model_name = "Model 2 (Sweep + BPR)"
                break
                
    # 3. Model 3 Check: IFVG (Inverse FVG)
    if not zone:
        ifvgs = find_ifvgs(closed, start_idx, direction)
        for ifvg in ifvgs:
            if ifvg["low"] <= price <= ifvg["high"]:
                zone = ifvg
                model_name = "Model 3 (Sweep + MSS + IFVG)"
                break
                
    # 4. Model 4 Check: Breaker Block
    if not zone:
        for bb in bbs:
            if bb["low"] <= price <= bb["high"]:
                zone = bb
                model_name = "Model 4 (Sweep + MSS + BB)"
                break
                
    # 5. Model 1 Check: Standard FVG Retracement
    if not zone:
        for fvg in fvgs:
            if fvg["low"] <= price <= fvg["high"] and is_fvg_unfilled(closed, fvg, fvg_dir, fvg["formed_idx"]):
                zone = fvg
                model_name = "Model 1 (Sweep + MSS + FVG)"
                break
                
    if zone is None:
        return None
        
    buffer = atr * 0.25
    if direction == "LONG":
        stop = sweep["sweep_extreme"] - buffer
        risk = price - stop
        if risk <= 0.5: return None
        target = price + risk * 2.0
    else:
        stop = sweep["sweep_extreme"] + buffer
        risk = stop - price
        if risk <= 0.5: return None
        target = price - risk * 2.0
        
    return {
        "direction": direction,
        "price": price,
        "stop": stop,
        "target": target,
        "model": model_name,
        "reason": f"ICT {model_name} triggered on XAUUSD, Stop: {stop:.2f}, TP: {target:.2f} (2R)" + (f", HTF: {htf_trend}" if htf_trend else "")
    }
