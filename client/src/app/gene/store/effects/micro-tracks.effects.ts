// Angular
import { Injectable } from '@angular/core';
// store
import { Store } from '@ngrx/store';
import * as fromRoot from '@gcv/gene/store/reducers';
import * as fromMicroTracks from '@gcv/gene/store/selectors/micro-tracks/';
import * as fromRouter from '@gcv/gene/store/selectors/router/';
import { Effect, Actions, ofType } from '@ngrx/effects';
import { combineLatest, of } from 'rxjs';
import { catchError, map, switchMap, withLatestFrom } from 'rxjs/operators';
import * as microTracksActions from '@gcv/gene/store/actions/micro-tracks.actions';
// app
import { Track } from '@gcv/gene/models';
import { ClusterMixin } from '@gcv/gene/models/mixins';
import { MicroTracksService } from '@gcv/gene/services';

@Injectable()
export class MicroTracksEffects {

  constructor(private actions$: Actions,
              private microTracksService: MicroTracksService,
              private store: Store<fromRoot.State>) { }

  // private

  // returns true if any of the tracks overlap with the given track
  private _tracksOverlap(track: Track, tracks: Track[]): boolean {
    const genes = new Set(track.genes);
    return tracks.some((t) => t.genes.some((g) => genes.has(g)));
  }

  // public

  // clear the store every time new parameters are emitted and search for tracks
  @Effect()
  clearTracks$ = this.store.select(fromRouter.getMicroQueryParams).pipe(
    withLatestFrom(
      this.store.select(
        fromMicroTracks.getClusteredAndAlignedSelectedMicroTracks),
      this.store.select(fromRouter.getSources)),
    switchMap(([params, {consensuses, tracks}, sources]) => {
      const clear = new microTracksActions.Clear();
      const actions: microTracksActions.Actions[] = [clear];
      consensuses.forEach((families, cluster) => {
        sources.forEach((source) => {
          const payload = {cluster, families, source, params};
          const action = new microTracksActions.Search(payload);
          actions.push(action);
        });
      });
      return actions;
    }),
  );

  // initializes a search whenever new aligned clusters are generated
  // TODO: update so it only gets tracks that haven't been fetched already, e.g.
  // if a source is (de)selected
  @Effect()
  consensusSearch$ = combineLatest(
      this.store.select(
        fromMicroTracks.getClusteredAndAlignedSelectedMicroTracks),
      this.store.select(fromRouter.getSources)
  ).pipe(
    withLatestFrom(this.store.select(fromRouter.getMicroQueryParams)),
    switchMap(([[{consensuses, tracks}, sources], params]) => {
      const actions: microTracksActions.Actions[] = [];
      consensuses.forEach((families, cluster) => {
        sources.forEach((source) => {
          const payload = {cluster, families, source, params};
          const action = new microTracksActions.Search(payload);
          actions.push(action);
        });
      });
      return actions;
    }),
  );

  // search for similar tracks to the query
  @Effect()
  miroTracksSearch$ = this.actions$.pipe(
    ofType(microTracksActions.SEARCH),
    map((action: microTracksActions.Search) => action.payload),
    withLatestFrom(
      this.store.select(fromMicroTracks.getClusteredSelectedMicroTracks)),
    switchMap(([{cluster, families, source, params}, clusteredTracks]) => {
      const clusterTracks = clusteredTracks.filter((t: ClusterMixin) => {
          return t.cluster === cluster;
        });
      const mixin = (track: Track): (Track | ClusterMixin) => {
          track.source = source;
          const t = Object.create(track);
          t.cluster = cluster;
          return t;
        };
      return this.microTracksService.microTracksSearch(families, params, source)
      .pipe(
        map((tracks) => {
          tracks = tracks.filter((t) => !this._tracksOverlap(t, clusterTracks as Track[]));
          const payload = {cluster, source, tracks: tracks.map(mixin)};
          return new microTracksActions.SearchSuccess(payload);
        }),
        catchError((error) => {
          const payload = {cluster, families, source};
          return of(new microTracksActions.SearchFailure(payload));
        }),
      );
    })
  );

}