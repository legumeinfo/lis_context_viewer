// Angular
import { AfterViewInit,
         Component,
         ElementRef,
         Input,
         OnChanges,
         SimpleChanges,
         OnDestroy,
         ViewChild } from '@angular/core';

// App
import { Group } from '../../models/group.model';

declare var GCV: any;
declare var plot;
declare var contextColors: any;
declare var d3: any;

@Component({
  moduleId: module.id,
  selector: 'plot',
  template: '<div #plot></div>',
  styles: [ '' ]
})

export class PlotComponent implements AfterViewInit, OnChanges, OnDestroy {
  @Input() plot: Group;
  @Input() args: any;

  @ViewChild('plot') el: ElementRef;

  private _plot = undefined;
  private _id = '';

  ngAfterViewInit(): void {
    this._draw();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (this.plot !== undefined) {
      this._id = 'plot-' + this.plot.id;
      this.el.nativeElement.id = this._id;
    }
    this._draw();
  }

  ngOnDestroy(): void {
    this._destroy();
  }

  private _destroy(): void {
    if (this._plot !== undefined) {
      this._plot.destroy();
      this._plot = undefined;
    }
  }

  private _draw(): void {
    if (this.el !== undefined &&
    this.el.nativeElement.id !== '' &&
    this.plot !== undefined) {
      this._destroy();
      this._plot = new GCV.Plot(this._id, contextColors, this.plot, this.args);
    }
  }
}