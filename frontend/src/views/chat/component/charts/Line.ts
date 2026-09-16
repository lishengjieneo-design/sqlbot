import { BaseG2Chart } from '@/views/chat/component/BaseG2Chart.ts'
import type { ChartAxis, ChartData } from '@/views/chat/component/BaseChart.ts'
import type { G2Spec } from '@antv/g2'
import {
  checkIsPercent,
  getAxesWithFilter,
  processMultiQuotaData,
} from '@/views/chat/component/charts/utils.ts'

const BLUECARD_BLUE = '#3b82f6'

/** Adaptive decimals for chart point labels / tooltips. */
export function formatChartNumber(value: unknown, isPercent = false): string {
  if (value === undefined || value === null || value === '') return ''
  const n = typeof value === 'number' ? value : Number(String(value).replace(/,/g, ''))
  if (!Number.isFinite(n)) return String(value)
  if (isPercent) {
    return `${trimFixed(n, 2)}%`
  }
  const abs = Math.abs(n)
  if (abs >= 1000) {
    return Math.round(n).toLocaleString('en-US')
  }
  if (abs >= 1) {
    return trimFixed(n, 2)
  }
  if (abs >= 0.01) {
    return trimFixed(n, 4)
  }
  return trimFixed(n, 6)
}

function trimFixed(n: number, maxDp: number): string {
  const fixed = n.toFixed(maxDp)
  return fixed.replace(/\.?0+$/, '')
}

export class Line extends BaseG2Chart {
  constructor(id: string) {
    super(id, 'line')
  }

  init(axis: Array<ChartAxis>, data: Array<ChartData>) {
    super.init(axis, data)

    const axes = getAxesWithFilter(this.axis)

    if (axes.x.length == 0 || axes.y.length == 0) {
      console.debug({ instance: this })
      return
    }

    let config = {
      data: data,
      y: axes.y,
      series: axes.series,
    }
    if (axes.multiQuota.length > 0) {
      config = processMultiQuotaData(
        axes.x,
        config.y,
        axes.multiQuota,
        axes.multiQuotaName,
        config.data
      )
    }

    const x = axes.x
    const y = config.y
    const series = config.series
    const _data = checkIsPercent(y, config.data)
    const isSingleSeries = series.length === 0
    const useBlueSkin = this.bluecardSkin && isSingleSeries
    const yKey = y[0].value

    console.debug({ 'render-info': { x: x, y: y, series: series, data: _data }, instance: this })

    const gridStyle = this.bluecardSkin
      ? {
          lineDash: [4, 4],
          stroke: '#e5e6eb',
        }
      : undefined

    const children: any[] = []

    if (useBlueSkin) {
      children.push({
        type: 'area',
        encode: {
          x: x[0].value,
          y: yKey,
          shape: 'smooth',
        },
        style: {
          fill: `l(270) 0:#ffffff 1:${BLUECARD_BLUE}`,
          fillOpacity: 0.18,
        },
        tooltip: false,
      })
    }

    children.push({
      type: 'line',
      encode: {
        shape: 'smooth',
      },
      // Color via style only — do NOT encode color to a constant hex (G2 shows it as legend).
      style: useBlueSkin
        ? {
            stroke: BLUECARD_BLUE,
            lineWidth: 2,
          }
        : undefined,
      labels: this.showLabel
        ? [
            {
              text: (row: any) => formatChartNumber(row[yKey], _data.isPercent),
              style: {
                dx: -10,
                dy: -12,
                fill: useBlueSkin ? BLUECARD_BLUE : undefined,
                fontSize: 11,
              },
              transform: [
                { type: 'contrastReverse' },
                { type: 'exceedAdjust' },
                { type: 'overlapHide' },
              ],
            },
          ]
        : [],
      tooltip: (row: any) => {
        const formatted = formatChartNumber(row[yKey], _data.isPercent)
        if (series.length > 0) {
          return {
            name: row[series[0].value],
            value: formatted,
          }
        }
        return { name: y[0].name, value: formatted }
      },
    })

    children.push({
      type: 'point',
      style: useBlueSkin
        ? {
            fill: BLUECARD_BLUE,
            stroke: '#fff',
            lineWidth: 1,
          }
        : {
            fill: 'white',
          },
      encode: {
        size: useBlueSkin ? 3.5 : 1.5,
      },
      tooltip: false,
    })

    const options: G2Spec = {
      ...this.chart.options(),
      type: 'view',
      data: _data.data,
      encode: {
        x: x[0].value,
        y: yKey,
        // Only bind color channel when there is a real series field
        color: series.length > 0 ? series[0].value : undefined,
      },
      // Hide bogus single-series color legend (was showing "#3b82f6")
      legend: useBlueSkin || series.length === 0 ? false : undefined,
      scale: {
        x: {
          nice: true,
        },
        y: {
          nice: true,
          type: 'linear',
        },
      },
      axis: {
        x: {
          title: false,
          labelFontSize: 12,
          labelAutoHide: {
            type: 'hide',
            keepHeader: true,
            keepTail: true,
          },
          labelAutoRotate: false,
          labelAutoWrap: true,
          labelAutoEllipsis: true,
          ...(gridStyle
            ? {
                grid: true,
                gridStroke: gridStyle.stroke,
                gridLineDash: gridStyle.lineDash,
              }
            : {}),
        },
        y: {
          title: false,
          ...(gridStyle
            ? {
                grid: true,
                gridStroke: gridStyle.stroke,
                gridLineDash: gridStyle.lineDash,
              }
            : {}),
        },
      },
      children,
    } as G2Spec

    this.chart.options(options)
  }
}
