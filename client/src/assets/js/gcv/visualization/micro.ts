import { d3 }         from './d3';
import { Visualizer } from './visualizer';


/** The micro-synteny viewer. */
export class Micro extends Visualizer {

  // Private
  private distances: Array<any>;
  private left: number;
  private names: Array<any>;
  private right: number;
  private thickness: any;
  private ticks: Array<any>;
  private x: any;
  private y: any;

  // Constants
  private GLYPH_SIZE: number;

  /** Resizes the viewer and x scale. Will be decorated by other components. */
  protected resize() {
    var w = this.container.clientWidth,
        doublePad = 2 * this.PAD,
        halfGlyph = this.GLYPH_SIZE / 2,
        r1 = this.left + halfGlyph,
        r2 = w - (this.right + halfGlyph);
    this.viewer.attr('width', w);
    this.x.range([r1, r2]);
  }

  /**
    * Parses parameters and initializes variables.
    * @param {HTMLElement|string} el - ID of or the element itself where the
    * viewer will be drawn in.
    * @param {object} colors - D3 family-to-color map.
    * @param {object} data - The data the viewer will visualize.
    * @param {object} options - Optional parameters.
    */
  protected init(el, colors, data, options) {
    super.init(el, colors, data);
    this.GLYPH_SIZE = 30;
    // create the viewer
    var levels = data.groups.map(group => {
      return Math.max.apply(null, group.genes.map(gene => gene.y)) + 1;
    });
    var numLevels = levels.reduce((a, b) => a + b, 0),
        halfTrack = this.GLYPH_SIZE / 2,
        top = this.PAD + halfTrack,
        bottom = top + (this.GLYPH_SIZE * numLevels);
    this.viewer.attr('height', bottom + halfTrack);
    // compute the x scale, track names and locations, and line thickness
    var minX = Infinity,
        maxX = -Infinity;
    var minDistance = Infinity,
        maxDistance = -Infinity;
		this.names = [];
    this.ticks = [];
    var tick = 0;
    this.distances = [];
    for (var i = 0; i < this.data.groups.length; i++) {
      var group = this.data.groups[i],
          fminI = Infinity,
          fmaxI = -Infinity;
      this.ticks.push(tick);
      tick += levels[i];
      var distances = [];
      for (var j = 0; j < group.genes.length; j++) {
        var gene = group.genes[j],
            fmax = gene.fmax,
            fmin = gene.fmin,
            x = gene.x;
        fminI = Math.min.apply(null, [fminI, fmax, fmin]);
        fmaxI = Math.max.apply(null, [fmaxI, fmax, fmin]);
        minX = Math.min(minX, x);
        maxX = Math.max(maxX, x);
        if (j < group.genes.length - 1) {
          var nextGene = group.genes[j + 1],
              nextFmin = nextGene.fmin,
              nextFmax = nextGene.fmax;
          var dist = Math.min.apply(null, [
            Math.abs(fmin - nextFmin),
            Math.abs(fmax - nextFmin),
            Math.abs(fmin - nextFmax),
            Math.abs(fmax - nextFmin)
          ]);
          distances.push(dist);
          minDistance = Math.min(minDistance, dist);
          maxDistance = Math.max(maxDistance, dist);
        }
      }
      this.names.push(group.genus + ' ' + group.species + '___' + group.chromosome_name + ':' + fminI + '..' + fmaxI);
      this.distances.push(distances);
    }
    // initialize the x, y, and line thickness scales
    this.x = d3.scale.linear().domain([minX, maxX]);
    this.y = d3.scale.linear().domain([0, numLevels - 1])
               .range([top, bottom]);
    this.thickness = d3.scale.linear()
      .domain([minDistance, maxDistance])
      .range([.1, 5]);
    // parse optional parameters
    this.options                   = Object.assign({}, options);
    this.options.boldFirst         = this.options.boldFirst || false;
    this.options.highlight         = this.options.highlight || [];
    this.options.selectiveColoring = this.options.selectiveColoring;
    this.options.nameClick         = this.options.nameClick || function (y, i) { };
    this.options.geneClick         = this.options.geneClick || function (b) { };
    this.options.plotClick         = this.options.plotClick;
    this.options.autoResize        = this.options.autoResize || false;
    this.options.hoverDelay        = this.options.hoverDelay || 500;
    if (this.options.contextmenu)
      this.viewer.on('contextmenu', () => {
        this.options.contextmenu(d3.event);
      });
    if (this.options.click)
      this.viewer.on('click', () => {
        this.options.click(d3.event);
      });
    this.right = this.PAD;
    super.initResize();
  }

  /**
    * Creates a graphic containing a track's genes.
    * @param {number} i - The index of the track in the input data to draw.
    * @return {object} - D3 selection of the new track.
    */
  private drawTrack(i) {
    var obj = this,
        t = this.data.groups[i],
        y = this.ticks[i];
  	// make svg group for the track
    var track = this.viewer.append('g')
          .attr('data-micro-track', i.toString())
          .attr('data-chromosome', t.chromosome_name)
          .attr('data-genus-species', t.genus + ' ' + t.species),
        neighbors = [];
    // add the lines
    for (var j = 0; j < t.genes.length - 1; j++) {
      neighbors.push({a: t.genes[j], b: t.genes[j + 1]});
    }
    var lineGroups = track.selectAll('rail')
      .data(neighbors)
      .enter()
      .append('g')
      .attr('class', 'rail');
    // draw lines left to right to simplify resizing
    var lines = lineGroups.append('line')
      	.attr('class', 'line')
        .attr('stroke-width', function (n, j) {
          return obj.thickness(obj.distances[i][j]);
        })
      	.attr('x1', 0)
      	.attr('y1', function (n) {
          var height = Math.abs(obj.y(n.a.y) - obj.y(n.b.y));
          if (n.a.x <= n.b.x) {
            return (n.a.y < n.b.y) ? 0 : height;
          } return (n.a.y < n.b.y) ? height : 0;
        })
      	.attr('y2', function (n) {
          var height = Math.abs(obj.y(n.a.y) - obj.y(n.b.y));
          if (n.a.x <= n.b.x) {
            return (n.a.y < n.b.y) ? height : 0;
          } return (n.a.y < n.b.y) ? 0 : height;
        });
    // add tooltips to the lines
    var lineTips = lineGroups.append('text')
    	.attr('class', 'synteny-tip')
      .attr('text-anchor', 'end')
    	.text(function (n, j) { return obj.distances[i][j]; });
    // make the gene groups
  	var geneGroups = track.selectAll('gene')
      .data(t.genes)
  	  .enter()
  	  .append('g')
  	  .attr('class', 'gene')
      .attr('data-gene', g => g.id)
      .attr('data-family', g => g.family)
  	  .attr('transform', function (g) {
  	    return 'translate(' + obj.x(g.x) + ', ' + obj.y(y + g.y) + ')';
  	  })
  	  .style('cursor', 'pointer')
      .on('mouseover', function (g) {
        var gene = '.GCV [data-gene="' + g.id + '"]',
            family = '.GCV [data-family="' + g.family + '"]';
        var selection = d3.selectAll(gene + ', ' + family)
          .filter(function () {
            var d = this.getAttribute('data-gene');
            return d === null || d == g.id;
          });
        obj.beginHover(selection);
      })
  	  .on('mouseout', function (g) {
        var gene = '.GCV [data-gene="' + g.id + '"]',
            family = '.GCV [data-family="' + g.family + '"]';
        var selection = d3.selectAll(gene + ', ' + family)
          .filter(function () {
            var d = this.getAttribute('data-gene');
            return d === null || d == g.id;
          });
        obj.endHover(selection);
      })
  	  .on('click', (g) => obj.options.geneClick(g, t));
  	// add genes to the gene groups
  	var genes = geneGroups.append('path')
  	  .attr('d', d3.svg.symbol().type('triangle-up').size(200))
  	  .attr('class', function (g) {
  	  	if (obj.options.highlight.indexOf(g.name) != -1) {
  	  	  return 'point focus';
  	  	} else if (g.family == '') {
  	  	  return 'point no_fam';
  	  	} else if (obj.options.selectiveColoring !== undefined &&
        obj.options.selectiveColoring[g.family] == 1) {
  	  	  return 'point single';
  	  	} return 'point';
      })
  	  .attr('transform', function (g) {
        var orientation = (g.strand == 1) ? '90' : '-90';
        return 'rotate(' + orientation + ')';
      })
  	  .style('fill', function (g) {
  	  	if (g.family == '' ||
        (obj.options.selectiveColoring !== undefined &&
        obj.options.selectiveColoring[g.family] == 1)) {
  	  	  return '#ffffff';
  	  	} return obj.colors(g.family);
  	  });
    // draw the background highlight
    if (i % 2) {
      var highY = obj.y(y)+genes.node().getBBox().y - 4,
          height = track.node().getBBox().height - highY + 6;
      track.highlight = track.append('rect')
        .attr('y', highY)
        .attr('height', height)
        .attr('fill', '#e7e7e7')
        .moveToBack();
    }
    // add tooltips to the gene groups
    var geneTips = geneGroups.append('text')
      .attr('class', 'synteny-tip')
  	  .attr('text-anchor', 'end')
  	  .text(function (g) { return g.name + ': ' + g.fmin + ' - ' + g.fmax; })
    // how the track is resized
    track.resize = function (geneGroups, linesGroups, lines, lineTips) {
      var obj = this;
      geneGroups.attr('transform', function (g) {
        return 'translate(' + obj.x(g.x) + ', ' + obj.y(y + g.y) + ')';
  	  });
      lineGroups.attr('transform', function (n) {
        var left = Math.min(n.a.x, n.b.x),
            top = y + Math.min(n.a.y, n.b.y);
        return 'translate(' + obj.x(left) + ', ' + obj.y(top) + ')';
      });
      lines.attr('x2', function (n) {
        return Math.abs(obj.x(n.a.x) - obj.x(n.b.x));
      });
      lineTips.attr('transform', function (n) {
        var x = Math.abs(obj.x(n.a.x) - obj.x(n.b.x)) / 2,
            y = Math.abs(obj.y(n.a.y) - obj.y(n.b.y)) / 2;
        // awkward syntax FTW
        var transform = d3.transform(d3.select(this).attr('transform'));
        transform.translate = [x, y];
        return transform;
      });
      if (track.highlight !== undefined) {
        track.highlight.attr('width', this.viewer.attr('width'));
      }
    }.bind(this, geneGroups, lineGroups, lines, lineTips);
    // how tips are rotated so they don't overflow the view
    var tips = track.selectAll('.synteny-tip');
    track.adjustTips = function (tips, resize) {
      var vRect = obj.viewer.node().getBoundingClientRect();
      tips.classed('synteny-tip', false)
        .attr('transform', function (t) {
          var tRect = this.getBoundingClientRect(),
              h = Math.sqrt(Math.pow(tRect.width, 2) / 2),  // rotated height
              o = (tRect.bottom + h > vRect.bottom) ? h + 10 : -10;
          return 'translate(' + o + ', ' + (-o) + ') rotate(-45)';
        })
        .classed('synteny-tip', true);
      resize();
    }.bind(this, tips, track.resize);
    return track;
  }


  /**
    * Creates the y-axis, placing labels at their respective locations.
    * @return {object} - D3 selection of the y-axis.
    */
  private drawYAxis() {
    // construct the y-axes
    var axis = d3.svg.axis().scale(this.y)
      .orient('left')
      .tickValues(this.ticks)
      .tickFormat((y, i) => { return this.names[i]; });
    // draw the axes of the graph
    var yAxis = this.viewer.append('g')
      .attr('class', 'axis')
      .call(axis);
    yAxis.selectAll('text')
      .attr('class', (y, i) => {
        return (i == 0 && this.options.boldFirst) ? 'query ' : '';
      })
      .attr('data-micro-track', (y, i) => i.toString())
      .attr('data-chromosome', (y, i) => this.data.groups[i].chromosome_name)
  	  .style('cursor', 'pointer')
      .on('mouseover', (y, i) => {
        var iStr = i.toString(),
            micro = '.GCV [data-micro-track="' + iStr + '"]',
            name = this.data.groups[i].chromosome_name,
            chromosome = '.GCV [data-chromosome="' + name + '"]';
        var selection = d3.selectAll(micro + ', ' + chromosome)
          .filter(function () {
            var t = this.getAttribute('data-micro-track');
            return t === null || t == iStr;
          });
        this.beginHover(selection);
      })
      .on('mouseout', (y, i) => {
        var iStr = i.toString(),
            micro = '.GCV [data-micro-track="' + iStr + '"]',
            name = this.data.groups[i].chromosome_name,
            chromosome = '.GCV [data-chromosome="' + name + '"]';
        var selection = d3.selectAll(micro + ', ' + chromosome)
          .filter(function () {
            var t = this.getAttribute('data-micro-track');
            return t === null || t == iStr;
          });
        this.endHover(selection);
      })
      .on('click', (y, i) => {
        this.options.nameClick(this.data.groups[i]);
      });


    yAxis.selectAll('text').each(function() {

      var text = d3.select(this),
        words = text.text().split(/___/).reverse(),
        word,
        line = [],
        lineNumber = 0,
        lineHeight = 1.1, // ems
        y = text.attr("y"),
        first = true;

      text.attr('dy', 0);

      var dy = parseFloat(text.attr("dy"));

      while (word = words.pop()) {
        if (first) {
          text.text(word);
          first = false;
        }
        else {
          text.append("tspan").attr("x", text.attr('x')).attr("y", y).attr("dy", ++lineNumber * lineHeight + dy + "em").text(word);
        }
      }
    });
    return yAxis;
  }


  /**
    * Creates the plot y-axis, placing labels at their respective locations.
    * @return {object} - D3 selection of the plot y-axis.
    */
  private drawPlotAxis() {
    // construct the plot y-axes
    var axis = d3.svg.axis().scale(this.y)
      .orient('right')
      .tickValues(this.ticks)
      .tickFormat('plot');
    // draw the axes of the graph
    var plotYAxis = this.viewer.append('g')
      .attr('class', 'axis plot-axis')
      .call(axis);
    plotYAxis.selectAll('text')
  	  .style('cursor', 'pointer')
      .on('click', (y, i) => {
        this.options.plotClick(this.data.groups[i]);
      });
    return plotYAxis;
  }

  /** Draws the viewer. */
  protected draw() {
    // draw the y-axes
    var yAxis = this.drawYAxis();
    this.left = yAxis.node().getBBox().width + this.PAD;
    yAxis.attr('transform', 'translate(' + this.left + ', 0)');
    this.left += this.PAD;
    if (this.options.plotClick !== undefined) {
      var plotAxis = this.drawPlotAxis();
      this.right += plotAxis.node().getBBox().width + this.PAD;
      var obj = this;
      var resizePlotYAxis = function () {
        var x = obj.viewer.attr('width') - obj.right + obj.PAD;
        plotAxis.attr('transform', 'translate(' + x + ', 0)');
      }
      this.decorateResize(resizePlotYAxis);
    }
    this.resize();
    // draw the tracks
    var tracks = [];
    for (var i = 0; i < this.data.groups.length; i++) {
      // make the track and save it for the resize call
      tracks.push(this.drawTrack(i).moveToBack());
    }
    // decorate the resize function with that of the track
    var resizeTracks = function () {
      tracks.forEach(function (t, i) {
        t.resize();
      });
    }
    this.decorateResize(resizeTracks);
    // rotate the tips now that all the tracks have been drawn
    tracks.forEach(function (t, i) {
      t.adjustTips();
    });
    // move all tips to front
    this.viewer.selectAll('.synteny-tip').moveToFront();
    // create an auto resize iframe, if necessary
    if (this.options.autoResize) {
      this.resizer = this.autoResize(this.container, (e) => {
        this.resize();
      });
    }
    this.resize();
  }

  // Public

  /** Makes a copy of the SVG and inlines external GCV styles. */
  protected inlineCopy() {
    return super.inlineCopy((clone) => {
      clone.select('.plot-axis').remove();
    });
	}
}
