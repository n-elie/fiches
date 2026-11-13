(function() {
    'use strict';

    echarts.registerCustomSeries('massSpectrum', function(params, api) {
        const payload = params.itemPayload || {};
        const selected = new Set(payload.selected || []);
        const isSelected = selected.has(params.dataIndex);

        const barColor = payload.barColor || '#1e1e1e';
        const selectedColor = payload.selectedColor || '#1f77b4';
        const labelThreshold = payload.labelThreshold != null ? payload.labelThreshold : 5;

        const mz = api.value(0);
        const inten = api.value(1);

        const xPix = api.coord([mz, 0])[0];
        const yPix = api.coord([mz, inten])[1];
        const yBase = api.coord([mz, 0])[1];
        const half = 2;

        const children = [{
            type: 'rect',
            shape: {
                x: xPix - half,
                y: yPix,
                width: half * 2,
                height: Math.max(yBase - yPix, 0)
            },
            style: {
                fill: isSelected ? selectedColor : barColor
            },
            emphasis: {
                style: {
                    fill: 'red'
                }
            }
        }];

        if (inten > labelThreshold) {
            children.push({
                type: 'text',
                silent: true,
                style: {
                    text: mz.toFixed(4),
                    x: xPix,
                    y: yPix - 5,
                    textAlign: 'center',
                    textVerticalAlign: 'bottom',
                    fontSize: 9,
                    fill: isSelected ? selectedColor : '#333',
                    fontWeight: isSelected ? 'bold' : 'normal'
                }
            });
        }

        return {
            type: 'group',
            children
        };
    });

    window.MassSpectrum = {

        create: function(container, spectrum, options) {
            options = options || {};
            const i18n = options.i18n || {};
            const title = options.title || options.reference || '';
			const locale = options.locale || 'EN';

            const $container = $(container);

			spectrum = Array.isArray(spectrum) ? spectrum : [];
			const xMinOrig = spectrum.length ? Math.min(...spectrum.map(p => p.x)) - 5 : 0;
			const xMaxOrig = spectrum.length ? Math.max(...spectrum.map(p => p.x)) + 5 : 100;
			const yMaxOrig = spectrum.length ? Math.max(10, Math.ceil(Math.max(...spectrum.map(p => p.y)) * 1.1)) : 100;

            const chart = echarts.init($container[0], null, {
                renderer: 'svg', locale: locale
            });

            function getSelected() {
                const payload = chart.getOption().series[0].itemPayload || {};
                return new Set(payload.selected || []);
            }

            function setSelected(selected) {
                chart.setOption({
                    series: [{
                        itemPayload: {
                            selected: Array.from(selected)
                        }
                    }]
                });
            }

            const option = {
                animation: true,
                title: {
                    text: title,
                    left: 'center'
                },
                grid: {
                    left: 65,
                    right: 25,
                    top: 35,
                    bottom: 70
                },

                xAxis: {
                    type: 'value',
                    name: 'm/z',
                    nameLocation: 'middle',
                    nameGap: 28,
                    nameTextStyle: {
                        fontStyle: 'italic',
                        fontSize: 14
                    },
                    splitLine: {
                        show: false
                    },
                    axisLabel: {
                        formatter: v => v.toFixed(0)
                    }
                },

                yAxis: {
                    type: 'value',
                    name: i18n.intensity || 'Relative intensity (%)',
                    nameLocation: 'middle',
                    nameGap: 45,
                    min: 0,
                    max: yMaxOrig,
                    splitLine: {
                        show: true,
                        lineStyle: {
                            color: '#eee'
                        }
                    }
                },

                tooltip: {
                    trigger: 'item',
                    confine: true,
                    formatter: p => {
                        const [mz, inten] = p.value;
                        return `<i>m/z</i> <b>${mz.toFixed(4)}</b> — <b>${inten.toFixed(2)}</b> %`;
                    }
                },

                toolbox: {
					orient: 'vertical',
					left: 'right',
					top: 'top',
                    feature: {
                        dataZoom: {
                            yAxisIndex: 'none',
                            brushStyle: {
                                color: 'rgb(52, 152, 219, 0.3)'
                            }
                        },
                        restore: {
                            title: i18n.restoreZoom || 'Restore zoom'
                        },
                        mySpacer1: {
                            show: true,
                            title: ' ',
                            icon: 'path://',
                            onclick: function() {
                                return false;
                            }
                        },
                        mySelectAll: {
                            show: true,
                            title: i18n.selectAll || 'Select all',
                            icon: 'path://m74.3164 90.752v10.4551h10.625V90.752Zm8.4021 2.3303-4.3429 4.3434-2.4365-2.4365-.4243.4243 2.8608 2.8608 4.7682-4.7677z',
                            onclick: function() {
                                const selected = new Set();
                                spectrum.forEach((p, i) => {
                                    if (p.y > 0) selected.add(i);
                                });
                                setSelected(selected);
                            }
                        },
                        myClearSelection: {
                            show: true,
                            title: i18n.clearSelection || 'Clear selection',
                            icon: 'path://M6 6l12 12M18 6L6 18',
                            onclick: function() {
                                setSelected(new Set());
                            }
                        },
                        mySpacer2: {
                            show: true,
                            title: ' ',
                            icon: 'path://',
                            onclick: function() {
                                return false;
                            }
                        },
                        dataView: {
                            readOnly: true
                        },
                        saveAsImage: {}
                    }
                },

                dataZoom: [{
                    type: 'inside',
                    xAxisIndex: 0,
                    zoomOnMouseWheel: true,
                    moveOnMouseMove: false,
                    moveOnMouseWheel: true,
                    startValue: xMinOrig,
                    endValue: xMaxOrig
                }],

                series: [{
                    type: 'custom',
                    renderItem: 'massSpectrum',
                    data: spectrum.map(p => [p.x, p.y]),
                    encode: {
                        x: 0,
                        y: 1
                    },
                    name: 'm/z\tIntensities (%)',
                    itemPayload: {
                        selected: [],
                        barColor: '#1e1e1e',
                        selectedColor: '#1f77b4',
                        labelThreshold: 5
                    }
                }]
            };

            chart.setOption(option);
            chart.dispatchAction({
                type: 'takeGlobalCursor',
                key: 'dataZoomSelect',
                dataZoomSelectActive: true
            });

            function rescaleY() {
                const dz = chart.getOption().dataZoom[0];
                const x0 = (dz.startValue !== undefined && dz.startValue !== null) ? dz.startValue : xMinOrig;
                const x1 = (dz.endValue !== undefined && dz.endValue !== null) ? dz.endValue : xMaxOrig;

                const visible = spectrum.filter(p => p.x >= x0 && p.x <= x1);
                const newMax = visible.length ?
                    Math.max(10, Math.ceil(Math.max(...visible.map(p => p.y)) * 1.1)) :
                    yMaxOrig;

                const curMax = chart.getOption().yAxis[0].max;
                if (curMax !== newMax) {
                    chart.setOption({
                        yAxis: {
                            max: newMax
                        }
                    });
                }
            }

            chart.on('dataZoom', rescaleY);

            function resetZoom() {
                chart.setOption({
                    dataZoom: [{
                        startValue: xMinOrig,
                        endValue: xMaxOrig
                    }],
                    yAxis: {
                        max: yMaxOrig
                    }
                });
            }

            $container.on('dblclick', resetZoom);

            let lastClickedIndex = null;
            chart.on('click', {
                seriesIndex: 0
            }, function(params) {
                const idx = params.dataIndex;

                if (!spectrum[idx] || spectrum[idx].y <= 0) return;

                const selected = getSelected();

                if (params.event && params.event.event.shiftKey && lastClickedIndex !== null) {
                    const [a, b] = [lastClickedIndex, idx].sort((x, y) => x - y);
                    for (let i = a; i <= b; i++) selected.add(i);
                } else if (params.event && params.event.event.ctrlKey) {
                    selected.has(idx) ? selected.delete(idx) : selected.add(idx);
                } else {
                    selected.has(idx) && selected.size === 1 ?
                        selected.clear() :
                        (selected.clear(), selected.add(idx));
                }
                lastClickedIndex = idx;

                setSelected(selected);
            });

            return chart;
        }
    };
})();