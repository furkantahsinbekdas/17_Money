import React, { useEffect, useRef, useCallback } from 'react';
import { createChart, CrosshairMode } from 'lightweight-charts';
import './Chart.css';

function Chart({ klines, technicalData }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const ema20Ref = useRef(null);
  const ema50Ref = useRef(null);

  const initChart = useCallback(() => {
    if (!containerRef.current || chartRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      layout: {
        background: { color: '#0f1319' },
        textColor: '#57636f',
        fontSize: 11,
        fontFamily: "'IBM Plex Mono', monospace",
        attributionLogo: false,   // sol alttaki TradingView logosunu kaldır
      },
      // Zaman ekseni etiketlerini YEREL saatte göster (UTC değil)
      localization: {
        timeFormatter: (t) => {
          const d = new Date(t * 1000);
          return d.toLocaleString('tr-TR', {
            day: '2-digit', month: '2-digit',
            hour: '2-digit', minute: '2-digit',
          });
        },
      },
      grid: {
        vertLines: { color: '#161d2733' },
        horzLines: { color: '#161d2733' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#e8a33d55', width: 1, style: 2 },
        horzLine: { color: '#e8a33d55', width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: '#1f2835',
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      timeScale: {
        borderColor: '#1f2835',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
        barSpacing: 8,           // mumlar arası daha geniş → saat etiketleri sığar
        // eksen üzerindeki saat etiketleri de yerel saatle
        tickMarkFormatter: (t) => {
          const d = new Date(t * 1000);
          return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
        },
      },
      handleScroll: { vertTouchDrag: false },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#27c28a',
      downColor: '#f0494f',
      borderUpColor: '#27c28a',
      borderDownColor: '#f0494f',
      wickUpColor: '#27c28a88',
      wickDownColor: '#f0494f88',
    });

    const ema20 = chart.addLineSeries({
      color: '#5b9dd9',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });

    const ema50 = chart.addLineSeries({
      color: '#f59e0b',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    ema20Ref.current = ema20;
    ema50Ref.current = ema50;

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    };

    window.addEventListener('resize', handleResize);

    const ro = new ResizeObserver(handleResize);
    ro.observe(containerRef.current);

    return () => {
      window.removeEventListener('resize', handleResize);
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      ema20Ref.current = null;
      ema50Ref.current = null;
    };
  }, []);

  useEffect(() => {
    const cleanup = initChart();
    return cleanup;
  }, [initChart]);

  useEffect(() => {
    if (!klines.length || !candleSeriesRef.current) return;

    const candleData = klines.map(k => ({
      time: Math.floor(new Date(k.open_time).getTime() / 1000),
      open: k.open,
      high: k.high,
      low: k.low,
      close: k.close,
    }));

    candleSeriesRef.current.setData(candleData);

    if (candleData.length >= 20 && ema20Ref.current) {
      ema20Ref.current.setData(calcEMA(candleData, 20));
    }
    if (candleData.length >= 50 && ema50Ref.current) {
      ema50Ref.current.setData(calcEMA(candleData, 50));
    }

    // OB ve FVG marker'ları
    const markers = [];

    if (technicalData?.order_blocks) {
      technicalData.order_blocks.forEach(ob => {
        const dataIdx = Math.max(0, candleData.length - 50 + ob.index);
        if (dataIdx < candleData.length) {
          markers.push({
            time: candleData[dataIdx].time,
            position: ob.type === 'bullish' ? 'belowBar' : 'aboveBar',
            color: ob.type === 'bullish' ? '#10b981' : '#ef4444',
            shape: 'square',
            text: 'OB',
          });
        }
      });
    }

    if (technicalData?.fvg) {
      technicalData.fvg.forEach(fvg => {
        const dataIdx = Math.max(0, candleData.length - 30 + fvg.index);
        if (dataIdx < candleData.length) {
          markers.push({
            time: candleData[dataIdx].time,
            position: fvg.type === 'bullish' ? 'belowBar' : 'aboveBar',
            color: fvg.type === 'bullish' ? '#3b82f6' : '#f59e0b',
            shape: 'circle',
            text: 'FVG',
          });
        }
      });
    }

    markers.sort((a, b) => a.time - b.time);

    const uniqueMarkers = [];
    const seen = new Set();
    for (const m of markers) {
      const key = `${m.time}-${m.position}`;
      if (!seen.has(key)) {
        seen.add(key);
        uniqueMarkers.push(m);
      }
    }

    candleSeriesRef.current.setMarkers(uniqueMarkers);

    if (chartRef.current) {
      chartRef.current.timeScale().scrollToRealTime();
    }
  }, [klines, technicalData]);

  return (
    <div className="chart-container" ref={containerRef} />
  );
}

function calcEMA(data, period) {
  const k = 2 / (period + 1);
  const result = [];
  let ema = null;

  for (const candle of data) {
    if (ema === null) {
      ema = candle.close;
    } else {
      ema = candle.close * k + ema * (1 - k);
    }
    result.push({ time: candle.time, value: ema });
  }

  return result.slice(period - 1);
}

export default Chart;
