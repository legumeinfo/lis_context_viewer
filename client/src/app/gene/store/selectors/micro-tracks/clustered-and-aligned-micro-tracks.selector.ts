// NgRx
import { createSelector } from '@ngrx/store';
// store
import { State } from '@gcv/gene/store/reducers/micro-tracks.reducer';
import * as fromRouter from '@gcv/gene/store/selectors/router/';
import { getMicroTracksState } from './micro-tracks-state.selector';
import { getSelectedMicroTracks } from './selected-micro-tracks.selector';
// app
import * as clusterfck from '@gcv-assets/js/clusterfck';
import { GCV } from '@gcv-assets/js/gcv';
import { ALIGNMENT_ALGORITHMS } from '@gcv/gene/algorithms';
import { AlignmentParams, Track } from '@gcv/gene/models';
import { AlignmentMixin, ClusterMixin } from '@gcv/gene/models/mixins';


// clustered


// clusters micro tracks based on their families
// TODO: update params to work with new clusterer
// TODO: only cluster when selectedLoaded emits true
export const getClusteredSelectedMicroTracks = createSelector(
  getSelectedMicroTracks,
  (tracks: Track[]): (Track | ClusterMixin)[] => {
    const metric = (a: Track, b: Track): number => {
        const f1 = a.families;
        const f2 = b.families;
        const f3 = [...f2].reverse();
        const d1 = GCV.metrics.levenshtein(f1, f2);
        const d2 = GCV.metrics.levenshtein(f1, f3);
        return Math.min(d1, d2);
      };
    const clusters = clusterfck.hcluster(tracks, metric,
      clusterfck.AVERAGE_LINKAGE, 10);
    const recurrence = (cluster) => {
        const elements = [];
        if ('left' in cluster || 'right' in cluster) {
          if ('left' in cluster) {
            elements.push(...recurrence(cluster['left']));
          }
          if ('right' in cluster) {
            elements.push(...recurrence(cluster['right']));
          }
        } else {
          elements.push(cluster['value']);
        }
        return elements;
      };
    const mixin = (i) => {
        return (t) => {
          const t2 = Object.create(t);
          t2.cluster = i;
          return t2;
        };
      };
    const reducer = (accumulator, cluster, i) => {
        const clusterTracks = recurrence(cluster).map(mixin(i));
        accumulator.push(...clusterTracks);
        return accumulator;
      };
    const clusteredTracks = clusters.reduce(reducer, []);
    return clusteredTracks;
  }
);

export const getSelectedMicroTracksForCluster = (id: number) => createSelector(
  getClusteredSelectedMicroTracks,
  (tracks: (Track | ClusterMixin)[]): (Track | ClusterMixin)[] => {
    const filteredTracks = tracks.filter((t: ClusterMixin) => t.cluster === id);
    return filteredTracks;
  }
);

export const getClusterIDs = createSelector(
  getClusteredSelectedMicroTracks,
  (tracks: (Track | ClusterMixin)[]): number[] => {
    const IDs = tracks.map((t: ClusterMixin) => t.cluster);
    const uniqueIDs = new Set(IDs);
    return Array.from(uniqueIDs);
  },
);


// clustered and aligned


// performs a multiple sequence alignment of the selected tracks in each cluster
// and outputs the aligned tracks and their consensus sequence
export const getClusteredAndAlignedSelectedMicroTracks = createSelector(
  getClusteredSelectedMicroTracks,
  (tracks: (Track | ClusterMixin)[]):
  {
    consensuses: string[][],
    tracks: (Track | ClusterMixin | AlignmentMixin)[]
  } => {
    // group tracks by cluster
    const clusterer = (accumulator, track) => {
        if (!(track.cluster in accumulator)) {
          accumulator[track.cluster] = [];
        }
        accumulator[track.cluster].push(track);
        return accumulator;
      };
    const clusters = tracks.reduce(clusterer, {});
    // multiple align each cluster's tracks
    const aligner = (accumulator, [i, tracks]) => {
        // prepare the data
        const trackFamilies = tracks.map((t) => t.families);
        const l = trackFamilies[0].length;
        const flattenedTracks = [].concat.apply([], trackFamilies);
        const characters = new Set(flattenedTracks);
        const omit = new Set();
        // construct and train the model
        const hmm = new GCV.graph.MSAHMM(l, characters);
        hmm.train(trackFamilies, {reverse: true, omit, surgery: true});
        // align the tracks
        const alignments = trackFamilies.map((f) => hmm.align(f));
        const mixin = (t, i) => {
            const t2 = Object.create(t);
            t2.alignment = alignments[i];
            return t2;
          };
        const alignedTracks = tracks.map(mixin);
        const consensus = hmm.consensus();
        accumulator.consensuses[i] = hmm.consensus();
        accumulator.tracks.push(...alignedTracks);
        return accumulator;
      };
    const clusteredAlignments = {
        consensuses: new Array(Object.keys(clusters).length),
        tracks: []
      };
    const alignedClusters =
      Object.entries(clusters).reduce(aligner, clusteredAlignments);
    return clusteredAlignments;
  },
);

// pairwise aligns each search result track to its cluster's consensus track
export const getClusteredAndAlignedSearchMicroTracks = createSelector(
  getMicroTracksState,
  getClusteredAndAlignedSelectedMicroTracks,
  fromRouter.getMicroAlignmentParams,
  (state: State, {consensuses, tracks}, params: AlignmentParams):
  (Track | ClusterMixin | AlignmentMixin)[] => {
    // get selected alignment algorithm
    const algorithmIDs = ALIGNMENT_ALGORITHMS.map((a) => a.id);
    const algorithmID = algorithmIDs.indexOf(params.algorithm);
    const algorithm = ALIGNMENT_ALGORITHMS[algorithmID].algorithm;
    // creates an alignment mixin for the given track
    const mixin = (track, alignment) => {
        const t = Object.create(track);
        t.alignment = alignment.alignment;
        t.score = alignment.score;
        return t;
      };
    // returns one or more alignments (depending on the alignment algorithm) for
    // the given sequence relative to the given reference
    const aligner = (reference, sequence) => {
        const options = {
            omit: new Set(''),
            scores: Object.assign({}, params),
          };
        const alignments = algorithm(reference, sequence);
        // TODO: combine repeat tracks
        return alignments;
      };
    // aligns each track to its cluster's consensus sequence, creates an
    // alignment mixin for each track's alignments, and return a flattened array
    const reducer = (accumulator, track) => {
        const cluster = (track as ClusterMixin).cluster;
        const consensus = consensuses[cluster];
        const families = (track as Track).families;
        const alignments = aligner(consensus, families);
        const trackAlignments = alignments.map((a) => mixin(track, a));
        accumulator.push(...trackAlignments);
        return accumulator;
      };
    // align the tracks
    const searchTracks = Object.values(state.entities);
    const alignedTracks = searchTracks.reduce(reducer, []);
    return alignedTracks;
  },
);

export const getAllClusteredAndAlignedMicroTracks = createSelector(
  getClusteredAndAlignedSelectedMicroTracks,
  getClusteredAndAlignedSearchMicroTracks,
  ({consensuses, tracks}, searchTracks):
  (Track | ClusterMixin | AlignmentMixin)[] => {
    return tracks.concat(searchTracks);
  },
);

export const getAlignedMicroTrackCluster = (id: number) => createSelector(
  getAllClusteredAndAlignedMicroTracks,
  (tracks) => {
    const cluster = tracks.filter((t: ClusterMixin) => t.cluster === id);
    return cluster;
  },
);
