#   Copyright 2019 APriori Investments
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import object_database.web.cells as cells

from research_app.Displayable import Display
from research_app.util.Timer import Timer

import research_app
import logging
import numpy

colors = [
    "#FF0000",
    "#00FF00",
    "#0000FF"
    ]

def nthColor(i):
    """Generate an infinite color map."""
    if i < len(colors):
        return colors[i]

    c1 = colors[i % len(colors)]
    c2 = nthColor(i // len(colors))

    return "#" + hex((int(c1[1:],16) + int(c2[1:],16)) // 2)[2:]

@cells.registerDisplay(Display.Plot)
def displayForPlot(display):
    # grab a context object, which tells us how we should filter our cube data for display purposes.
    # this must be pushed on the stack above us for us to display properly.
    datasetStatesUnnamed = display.args
    datasetStatesNamed = display.kwargs

    def downsamplePlotData(linePlot):
        data = {}

        if len(datasetStatesUnnamed) <= 1:
            for ds in datasetStatesUnnamed:
                data.update(makePlotData(ds,"","series"))
        else:
            for i, ds in enumerate(datasetStatesUnnamed):
                data.update(makePlotData(ds,"","series_" + str(i+1)))

        for name, ds in datasetStatesNamed.items():
            data.update(makePlotData(ds, name + ":", name))

        with Timer("Downsampling plot data"):
            #because of slow connection speeds, lets not send more than MAX_POINTS_PER_CHART points total
            seriesCount = len(data)
            if seriesCount == 0:
                return data

            #first, restrict the dataset to what the xy can hold
            if linePlot.curXYRanges.get() is not None:
                minX, maxX = linePlot.curXYRanges.get()[0]

                for series in data:
                    dim = 'timestamp' if 'timestamp' in data[series] else 'x'
                    indexLeft = (
                        max(0,data[series][dim].searchsorted(minX - (maxX-minX)/2)) if minX is not None else 0
                        )
                    indexRight = (
                        min(data[series][dim].searchsorted(maxX + (maxX-minX)/2, 'right'), len(data[series][dim]))
                            if maxX is not None else 0
                        )

                    data[series][dim] = data[series][dim][indexLeft:indexRight]
                    data[series]['y'] = data[series]['y'][indexLeft:indexRight]

            #now check our output point count
            totalPoints = sum(len(data[series]['y']) for series in data)

            colorIx = 0

            if totalPoints > 10000 or candlestick.get():
                with Timer("Downsampling %s total points", totalPoints):
                    if candlestick.get():
                        downsampleRatio = int(numpy.ceil(totalPoints / (500*len(data))))
                    else:
                        downsampleRatio = int(numpy.ceil(totalPoints / (2000*len(data))))

                    for series in data:
                        dim = 'timestamp' if 'timestamp' in data[series] else 'x'

                        samplePoints = numpy.arange(len(data[series][dim]) // downsampleRatio) * downsampleRatio

                        if candlestick.get():
                            # take the average of the points in the middle
                            data[series][dim] = (
                                numpy.add.reduceat(data[series][dim], samplePoints) /
                                numpy.add.reduceat(data[series][dim] * 0 + 1, samplePoints)
                                )
                            data[series]['open'] = data[series]['y'][samplePoints[:-1]]
                            data[series]['close'] = data[series]['y'][samplePoints[1:]-1]
                            data[series]['high'] = numpy.maximum.reduceat(data[series]['y'], samplePoints)
                            data[series]['low'] = numpy.minimum.reduceat(data[series]['y'], samplePoints)
                            data[series]['decreasing'] = data[series]['increasing'] = {'line': {'color': nthColor(colorIx)}}
                            colorIx += 1
                            del data[series]['y']
                            data[series]['type'] = 'candlestick'
                        else:
                            data[series]['line'] = {'color': nthColor(colorIx)}
                            data[series][dim] = data[series][dim][samplePoints[1:]-1]
                            data[series]['y'] = data[series]['y'][samplePoints[1:]-1]
                            colorIx += 1

            else:
                for series in data:
                    data[series]['line'] = {'color': nthColor(colorIx)}
                    colorIx += 1

        return data

    def makePlotData(toShow, prefix, emptySeriesName):
        return {emptySeriesName: {'x': numpy.arange(len(toShow)), 'y': toShow}}

    showChart = cells.Slot(True)
    candlestick = cells.Slot(False)

    def cardContents():
        if showChart.get():
            xySlot = cells.Slot()

            return cells.Plot(downsamplePlotData, xySlot=xySlot).width("100%")
        else:
            seq = []
            for plottedSet in list(display.unnamed) + list(display.named.values()):
                seq.append(research_app.DisplayForDataset.displayForDataset(
                    DatasetDisplay.Dataset(dataset=plottedSet)
                    )
                )
            return cells.Sequence(seq)


    res = cells.Card(cells.Subscribed(cardContents),
        header=cells.HeaderBar(
            [cells.Text(display.title)] if display.title else [],
            [],
            [
            cells.Subscribed(lambda:
                cells.Button("Show Candlestick", lambda: candlestick.set(not candlestick.get()), active=candlestick.get())
                    if showChart.get() else None
                ),
            cells.Subscribed(lambda:
                cells.ButtonGroup([
                    cells.Button(cells.Octicon("graph"), lambda: showChart.set(True), active=showChart.get()),
                    cells.Button(cells.Octicon("three-bars"), lambda: showChart.set(False), active=not showChart.get())
                    ])
                )
            ])
        )

    return res
