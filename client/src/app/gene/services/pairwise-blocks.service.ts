// Angular
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
// store
import { Store, select } from '@ngrx/store';
import * as pairwiseBlocksActions
  from '@gcv/gene/store/actions/pairwise-blocks.actions';
import * as routerActions from '@gcv/store/actions/router.actions';
import * as fromRoot from '@gcv/store/reducers';
import * as fromPairwiseBlocks from '@gcv/gene/store/selectors/pairwise-blocks/';
// app
import { PairwiseBlocks, PairwiseBlock, Track } from '@gcv/gene/models';
import { BlockParams } from '@gcv/gene/models/params';
import { HttpService } from '@gcv/core/services/http.service';


type RawPairwiseBlocks = {
  chromosome: string,
  genus: string,
  species: string,
  blocks: PairwiseBlock[],
};


@Injectable()
export class PairwiseBlocksService extends HttpService {

  constructor(private _http: HttpClient, private _store: Store<fromRoot.State>) {
    super(_http);
  }

  getPairwiseBlocks(
    chromosome: Track,
    blockParams: BlockParams,
    serverID: string,
    targets: string[] = []):
  Observable<PairwiseBlocks[]> {
    const body = {
      chromosome: chromosome.families,
      intermediate: blockParams.bintermediate,
      mask: blockParams.bmask,
      matched: blockParams.bmatched,
      targets,
    };
    return this._makeRequest<{blocks: RawPairwiseBlocks[]}>(serverID, 'blocks', body).pipe(
      map((result) => {
        const blocks = result.blocks.map((block) => {
          return {
            reference: chromosome.name,
            referenceSource: chromosome.source,
            chromosome: block.chromosome,
            chromosomeSource: serverID,
            chromosomeGenus: block.genus,
            chromosomeSpecies: block.species,
            blocks: block.blocks,
          };
        });
        return blocks;
      }),
      catchError((error) => throwError(error)),
    );
  }

  getPairwiseBlocksForTracks(
    tracks: Track[],
    sources: string[],
    params: BlockParams,
    // TODO: targets should specify sources
    targets: string[] = []):
  Observable<PairwiseBlocks[]> {
    const trackActions = tracks.map((t) => {
        return sources.map((s) => {
          const payload = {chromosome: t, source: s, params, targets};
          return new pairwiseBlocksActions.Get(payload);
        });
      });
    trackActions.forEach((ta) => ta.forEach((a) => this._store.dispatch(a)));
    const targetSet = new Set(targets);
    return this._store.pipe(
      select(
        fromPairwiseBlocks
          .getFilteredAndOrderedPairwiseBlocksForTracks(tracks, sources)
      ),
      // TODO: there should be a selector for this
      map((blocks) => {
        if (targetSet.size == 0) {
          return blocks;
        }
        return blocks.filter((b) => targetSet.has(b.chromosome));
      }),
    );
  }

  updateParams(params: BlockParams): void {
    const path = [];
    const query = Object.assign({}, params);
    this._store.dispatch(new routerActions.Go({path, query}));
  }
}
