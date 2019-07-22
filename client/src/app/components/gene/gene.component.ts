// Angular
import { Component, ViewChild } from "@angular/core";
// app
import { GoldenLayoutDirective } from "../../directives";
import { MacroComponent } from "./macro.component";
import { MicroComponent } from "./micro.component";
import { PlotComponent } from "./plot.component";

@Component({
  selector: "gene",
  styleUrls: ["./gene.component.scss"],
  templateUrl: "./gene.component.html",
})
export class GeneComponent {

  @ViewChild(GoldenLayoutDirective) goldenLayoutDirective;

  layoutComponents = [
      {component: MacroComponent, name: "macro"},
      {component: MicroComponent, name: "micro"},
      {component: PlotComponent, name: "plot"}
    ];
  layoutConfig = {
      content: [{
        type: "column",
        content: [
          {
            type: "component",
            componentName: "macro",
            isClosable: false
          },
          {
            type: "component",
            componentName: "micro",
            componentState: {
              inputs: {key: "value"},
              outputs: {
                plot: (() => {
                  this.goldenLayoutDirective.addItem({type: "component", componentName: "plot"});
                })
              },
            },
            isClosable: false
          }
        ]
      }]
    };
}