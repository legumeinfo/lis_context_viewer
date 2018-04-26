# Django
from django.db.backends.signals   import connection_created
from django.db.models             import F, Func, Q
from django.dispatch              import receiver
from django.http                  import Http404, HttpResponse, \
    HttpResponseBadRequest
from django.shortcuts             import get_object_or_404, render
from django.utils.http            import http_date
from django.views.decorators.csrf import csrf_exempt

# services app
from services.models import Cv, Cvterm, Feature, Featureloc, Featureprop, \
    FeatureRelationship, GeneFamilyAssignment, GeneOrder, Organism, Phylonode

# Python
import json
import math
import operator
import time
from collections     import defaultdict, OrderedDict
from itertools       import chain
from multiprocessing import Pool as ThreadPool


# globals that store pre-loaded data
CHROMOSOME_FAMILY_COUNTS = None
CHROMOSOME_MAP = None
CHROMOSOMES_AS_FAMILIES = None
CHROMOSOMES_AS_GENES = None


# listen for ready signal from the database
@receiver(connection_created)
def db_ready_handler(sender, **kwargs):
    global CHROMOSOME_FAMILY_COUNTS, CHROMOSOME_MAP, CHROMOSOMES_AS_FAMILIES,\
        CHROMOSOMES_AS_GENES
    print 'Pre-loading macro-synteny data...'

    # get family assignment and number on chromosome for each gene
    families        = GeneFamilyAssignment.objects.all().iterator()
    gene_family_map = dict((f.gene_id, f.family_label) for f in families)
    gene_orders     = list(GeneOrder.objects.all()\
                        .order_by('chromosome_id', 'number'))

    # fetch all chromosomes
    chromosome_cvs = list(Cvterm.objects.filter(name='chromosome'))
    chromosomes = list(Feature.objects
        .only('feature_id', 'name', 'organism_id')
        .filter(type__in=chromosome_cvs))
    CHROMOSOME_MAP = dict((c.feature_id, c) for c in chromosomes)

    # construct various representations of chromosomes
    CHROMOSOMES_AS_GENES    = defaultdict(list)
    CHROMOSOMES_AS_FAMILIES = defaultdict(list)
    CHROMOSOME_FAMILY_COUNTS = defaultdict(lambda: defaultdict(int))
    for o in gene_orders:
        if o.chromosome_id in CHROMOSOME_MAP:
            CHROMOSOMES_AS_GENES[o.chromosome_id].append(o.gene_id)
            f = gene_family_map.get(o.gene_id, '')
            CHROMOSOMES_AS_FAMILIES[o.chromosome_id].append(f)
            CHROMOSOME_FAMILY_COUNTS[o.chromosome_id][f] += 1

    # only want to run on the initial database connection
    connection_created.disconnect(db_ready_handler)


# decorator for invalidating the cache every hour
def ensure_nocache(view):
    def wrapper(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        try:
            response['Cache-Control'] = 'max-age=3600, must-revalidate'
            response['Expires'] = http_date(time.time() + 3600)
        except:
            pass
        return response
    return wrapper


#########################################################
# these are services for the stand alone context viewer #
#########################################################

######
# v1 #
######

# returns contexts centered at genes in the list provided
@csrf_exempt
@ensure_nocache
def v1_micro_synteny_basic(request):
    # parse the POST data (Angular puts it in the request body)
    POST = json.loads(request.body)

    # make sure the request type is POST and that it contains a list of genes
    if request.method == 'POST' and 'genes' in POST and 'neighbors' in POST:
        # prepare a generic response
        generic = HttpResponse(
            json.dumps('{"families":[], "groups":[]}'),
            content_type='application/json; charset=utf8'
        )

        # how many genes will be displayed?
        num = POST['neighbors']
        try:
            num = int(num)
            if num <= 0:
                raise ValueError("neighbors can't be negative")
        except:
            return HttpResponseBadRequest()
        # get the focus genes
        focus_genes = Feature.objects.only('organism_id', 'name')\
        .filter(name__in=POST['genes'])
        if not focus_genes:
            return generic

        #######################
        # begin fetching data #
        #######################

        # what we'll use to construct the json
        groups = []
        families = {}

        # the gene_family cvterm
        y = 0
        family_term = list(Cvterm.objects.filter(name='gene family')[:1])[0]
        focus_family_id = None

        # get the focus gene locations
        focus_locs = Featureloc.objects.only(
            'feature_id',
            'srcfeature_id',
            'fmin',
            'fmax',
            'strand'
        ).filter(feature__in=focus_genes)
        focus_loc_map = dict((o.feature_id, o) for o in focus_locs)
        if not focus_loc_map:
            return generic

        # get the source feature names of the feature locs
        srcfeatures = Feature.objects.only('name').filter(
            pk__in=focus_locs.values_list('srcfeature_id', flat=True)
        )
        srcfeature_map = dict((o.pk, o) for o in srcfeatures)
        if not srcfeature_map:
            return generic

        # get the organisms for all the focus gene
        organisms = Organism.objects.only('genus', 'species').filter(
            pk__in=focus_genes.values_list('organism_id', flat=True)
        )
        organism_map = dict((o.pk, o) for o in organisms)
        if not organism_map:
            return generic

        # get the focus genes family ids
        family_ids = GeneFamilyAssignment.objects.only(
            'gene_id', 'family_label'
        ).filter(gene_id__in=focus_genes)
        family_map = dict((o.gene_id, o.family_label) for o in family_ids)
        if not family_map:
            return generic

        # get the orders for the focus genes
        orders = list(GeneOrder.objects.filter(gene__in=focus_genes))
        order_map = dict((o.gene_id, o) for o in orders)
        if not orders:
            return generic

        # get the orders for all the genes surrounding the focus genes
        gene_queries = dict((o.pk,
            Q(chromosome_id=o.chromosome_id,
              number__lte=o.number+num,
              number__gte=o.number-num)
            ) for o in orders)
        gene_pool = list(GeneOrder.objects.filter(
            reduce(operator.or_, gene_queries.values())
        ))
        gene_pool_ids = map(lambda g: g.gene_id, gene_pool)
        group_by_chromosome = {}
        for g in gene_pool:
            if g.chromosome_id not in group_by_chromosome:
                group_by_chromosome[g.chromosome_id] = [g]
            else:
                group_by_chromosome[g.chromosome_id].append(g)

        def getNumber(g):
            return g.number

        track_gene_map = {}
        for o in orders:
            if o.chromosome_id in group_by_chromosome:
                track_gene_map[o.pk] = []
                for g in group_by_chromosome[o.chromosome_id]:
                    if g.number <= o.number+num and g.number >= o.number-num:
                        track_gene_map[o.pk].append(g)
                track_gene_map[o.pk] = sorted(
                    track_gene_map[o.pk],
                    key=getNumber
                )

        # get the feature names for all the genes surrounding the focus genes
        feature_pool = Feature.objects.only('name')\
        .filter(pk__in=gene_pool_ids)
        feature_name_map = dict((o.pk, o.name) for o in feature_pool)

        # get feature locations for all the genes surrounding the focus genes
        loc_queries = dict((o.pk,
            Q(chromosome=o.chromosome_id,
              number__lte=o.number+num,
              number__gte=o.number-num)
            ) for o in orders)
        loc_pool = Featureloc.objects.only(
            'feature_id',
            'fmin',
            'fmax',
            'strand'
        ).filter(feature__in=gene_pool_ids)
        gene_loc_map = dict((o.feature_id, o) for o in loc_pool)
        track_loc_map = {}
        for o in orders:
            track_loc_map[o.pk] = []
            for g in track_gene_map[o.pk]:
                track_loc_map[o.pk].append(gene_loc_map[g.gene_id])
            track_loc_map[o.pk] = sorted(
                track_loc_map[o.pk],
                key=lambda loc: loc.fmin
            )

        # get the families for all the genes surrounding the focus genes
        gene_families = GeneFamilyAssignment.objects.only(
            'gene_id',
            'family_label'
        ).filter(gene_id__in=gene_pool_ids)
        gene_family_map = dict(
            (o.gene_id, o.family_label) for o in gene_families
        )

        #######################
        # begin generate json #
        #######################

        for gene in focus_genes:
            if gene.pk not in focus_loc_map:
                continue
            focus_loc = focus_loc_map[gene.pk]
            srcfeature = srcfeature_map[focus_loc.srcfeature_id]
            organism = organism_map[gene.organism_id]
            family_id = "" if gene.pk not in family_map else family_map[gene.pk]
            if len(family_id) > 0:
                focus_family_id = family_id
                if family_id not in families:
                    families[family_id] = ('{"name":"' + family_id +
                        '", "id":"' + family_id + '"}')
            group = ('{"chromosome_name":"' + srcfeature.name +
                '", "chromosome_id":' + str(srcfeature.feature_id) +
                ', "genus":"' + organism.genus +
                '", "species":"' + organism.species +
                '", "species_id":' + str(gene.organism_id)+', "genes":[')
            order = order_map[gene.pk]
            track_genes = track_gene_map[order.pk]
            track_locs = track_loc_map[order.pk]

            # add gene entries for the track_locs
            genes = []
            for l in track_locs:
                family_id = '' if l.feature_id not in gene_family_map\
                               else gene_family_map[l.feature_id]
                if family_id != '':
                    if family_id not in families:
                            families[family_id] = ('{"name":"' + family_id +
                                '", "id":"' + family_id + '"}')
                genes.append('{"name":"' + feature_name_map[l.feature_id] +
                             '", "id":' + str(l.feature_id) + ',' +
                             '"fmin":' + str(l.fmin) + ',' +
                             '"fmax":' + str(l.fmax) + ',' +
                             '"strand":' + str(l.strand) + ',' +
                             '"family":"' + family_id + '"}')
            group += ','.join(genes) + ']}'
            groups.append(group)

        # write the contents of the file
        view_json = ('{"families":[' + ','.join(families.values()) + '], "groups":[' +
            ','.join(groups) + ']}')

        return HttpResponse(
            json.dumps(view_json),
            content_type='application/json; charset=utf8'
        )
    return HttpResponseBadRequest()


# resolves a focus gene name to a query track
@csrf_exempt
@ensure_nocache
def v1_gene_to_query_track(request):
    # parse the POST data (Angular puts it in the request body)
    POST = json.loads(request.body)

    # make sure the request type is POST and that it contains a focus gene name
    if request.method == 'POST' and 'gene' in POST and 'neighbors' in POST:
        # get the focus gene of the query track
        focus = get_object_or_404(Feature, name=POST['gene'])
        focus_id = focus.pk
        focus_order = list(GeneOrder.objects.filter(gene=focus))
        if len(focus_order) == 0:
            raise Http404
        focus_order = focus_order[0]
        # how many neighbors should there be?
        num = POST['neighbors']
        try:
            num = int(num)
            if num <= 0:
                raise ValueError("neighbors can't be negative")
        except:
            return HttpResponseBadRequest()
        # get the gene family type
        gene_family_type = list(
            Cvterm.objects.only('pk').filter(name='gene family')
        )
        if len(gene_family_type) == 0:
            raise Http404
        gene_family_type = gene_family_type[0]

        #################################
        # begin - construct query track #
        #################################

        # get the neighbors of focus via their ordering
        neighbor_ids = list(GeneOrder.objects.filter(
            chromosome=focus_order.chromosome_id,
            number__gte=focus_order.number-num,
            number__lte=focus_order.number+num
        ).order_by('number').values_list('gene_id', flat=True))

        # actually get the gene families
        neighbor_families = list(GeneFamilyAssignment.objects.only(
            'gene_id',
            'family_label'
        ).filter(gene_id__in=neighbor_ids))
        neighbor_family_map = dict(
            (o.gene_id, o.family_label) for o in neighbor_families
        )
        family_ids = []
        query_families = {}
        for n in neighbor_family_map.values():
            if n not in family_ids:
                family_ids.append(n)
                query_families[n] = 1

        # make the query track
        # get the gene names
        neighbor_features = list(Feature.objects.only('name')\
            .filter(pk__in=neighbor_ids))
        neighbor_name_map = dict((o.pk, o.name) for o in neighbor_features)
        # get the gene flocs
        neighbor_flocs = list(Featureloc.objects.only(
            'feature_id',
            'fmin',
            'fmax',
            'strand'
        ).filter(feature__in=neighbor_ids))
        neighbor_floc_map = dict((o.feature_id, o) for o in neighbor_flocs)
        # get the track chromosome
        chromosome = list(Feature.objects.only('name', 'organism_id')\
            .filter(pk=neighbor_floc_map[int(focus.pk)].srcfeature_id))
        chromosome = chromosome[0]
        # get the track organism
        organism = list(Organism.objects.only('genus', 'species')\
            .filter(pk=chromosome.organism_id))
        organism = organism[0]
        # generate the json for the query genes
        genes = []
        query_align = []
        for i in range(len(neighbor_ids)):
            g = neighbor_ids[i]
            family = str(neighbor_family_map[g] ) if g in neighbor_family_map else ''
            floc = neighbor_floc_map[g]
            genes.append('{"name":"' + neighbor_name_map[g] + '", "id":' +
                str(g) + ', "family":"' + family + '", "fmin":' +
                str(floc.fmin) + ', "fmax":' + str(floc.fmax) + ', "strand":' +
                str(floc.strand) + ', "x":' + str(i) + ', "y":0}')
            query_align.append((g, family))
        query_group = ('{"genus":"' + organism.genus + '", "species":"' +
            organism.species + '", "species_id":' + str(organism.pk) +
            ', "chromosome_name":"' + chromosome.name + '", "chromosome_id":' +
            str(chromosome.pk) + ', "genes":[' + ','.join(genes) + ']}')

        return HttpResponse(
            json.dumps(query_group),
            content_type='application/json; charset=utf8'
        )
    return HttpResponseBadRequest()


# returns similar contexts to the families provided
@csrf_exempt
@ensure_nocache
def v1_micro_synteny_search(request):
    # parse the POST data (Angular puts it in the request body)
    POST = json.loads(request.body)

    # make sure the request type is POST and that it contains a query (families)
    if request.method == 'POST' and 'query' in POST and 'matched' in POST and 'intermediate' in POST:

        ###############################
        # begin - function parameters #
        ###############################

        # how many matched_families should there be?
        num_matched_families = POST['matched']
        try:
            num_matched_families = int(num_matched_families)
            if num_matched_families <= 0:
                raise ValueError("matched can't be negative")
        except:
            return HttpResponseBadRequest()
        # the number of non query family genes tolerated between each pair of
        # family genes
        non_family = POST['intermediate']
        try:
            non_family = int(non_family)
            if non_family < 0:
                raise ValueError("intermediate can't be negative")
        except:
            return HttpResponseBadRequest()
        # the number of non query family genes tolerated between each pair of
        # get the gene family type
        gene_family_type = list(
            Cvterm.objects.only('pk').filter(name='gene family')
        )
        if len(gene_family_type) == 0:
            raise Http404
        gene_family_type = gene_family_type[0]

        ##################
        # begin - search #
        ##################

        # find all genes with the same families (excluding the query genes)
        # huge loss of power here - should use some kind of indexed lookup instead
        # of the value field
        family_ids = POST['query']
        related_genes = list(GeneFamilyAssignment.objects.only(
            'gene_id',
            'family_label'
        ).filter(family_label__in=family_ids))
        gene_family_map = dict((o.gene_id, o.family_label) for o in related_genes)

        # get the orders (and chromosomes) of the genes
        related_orders = list(GeneOrder.objects.only(
            'gene_id',
            'number',
            'chromosome_id'
        ).filter(gene__in=gene_family_map.keys()))
        gene_order_map = dict((o.gene_id, o.number) for o in related_orders)
        # group the genes by their chromosomes
        chromosome_genes_map = {}
        for o in related_orders:
            if o.chromosome_id in chromosome_genes_map:
                chromosome_genes_map[o.chromosome_id].append(o.gene_id)
            else:
                chromosome_genes_map[o.chromosome_id] = [o.gene_id]

        # fetch all the chromosome names (organism_id and pk are implicit)
        chromosomes = Feature.objects.only('organism_id', 'name')\
            .filter(pk__in=chromosome_genes_map.keys())
        id_chromosome_map = dict((o.pk, o) for o in chromosomes)

        # fetch the chromosome organisms
        organism_ids = chromosomes.values_list('organism_id', flat=True)
        organisms = list(Organism.objects.only('genus', 'species')\
            .filter(pk__in=organism_ids))
        id_organism_map = dict((o.pk, o) for o in organisms)

        # construct tracks for each chromosome
        tracks = {}
        gene_queries = []
        for chromosome_id, genes in chromosome_genes_map.iteritems():
            if len(genes) < 2:
                continue
            # put the genes in order
            genes.sort(key=lambda g: gene_order_map[g])
            # find all disjoint subsets of the genes where all sequential genes in
            # the set are separated by no more than non_family non-query-family
            # genes
            block = [0]
            matched_families = set([gene_family_map[genes[0]]])
            # traverse the genes in the order they appear on the chromosome
            for i in range(1, len(genes)):
                g = genes[i]
                # add the gene to the current block if it meets the non query family
                # criteria
                gap_size = gene_order_map[g]-gene_order_map[genes[block[-1]]]-1
                if gap_size <= non_family:
                    matched_families.add(gene_family_map[g])
                    block.append(i)
                # otherwise, generate a track from the block and start a new block
                if gap_size > non_family or i == len(genes)-1:
                    # generate a track from the block
                    if len(matched_families) >= num_matched_families:
                        # get all the gene ids
                        tracks[
                            (chromosome_id, gene_order_map[genes[block[0]]],
                            gene_order_map[genes[block[-1]]])
                        ] = []
                        gene_queries.append(
                            Q(chromosome=chromosome_id,
                              number__gte=gene_order_map[genes[block[0]]],
                              number__lte=gene_order_map[genes[block[-1]]])
                        )
                    # start the next block
                    block = [i]
                    matched_families = set([gene_family_map[g]])

        # are there any queries to operate on?
        if len(gene_queries) != 0:
            # get the track genes
            gene_pool = list(GeneOrder.objects\
                .filter(reduce(operator.or_, gene_queries)))
            gene_ids = map(lambda x: x.gene_id, gene_pool)

            # get the track gene families
            track_gene_families = list(GeneFamilyAssignment.objects.only(
                'gene_id',
                'family_label'
            ).filter(gene_id__in=gene_ids))
            track_family_map = dict(
                (o.gene_id, o.family_label) for o in track_gene_families
            )

            # make sure all families are present in the json
            for f in track_family_map.values():
                if f not in family_ids:
                    family_ids.append(f)

            # get all the gene names
            gene_names = list(Feature.objects.only('name').filter(pk__in=gene_ids))
            gene_name_map = dict((o.pk, o.name) for o in gene_names)

            # get all the gene featurelocs
            gene_locs = list(Featureloc.objects.only(
                'feature_id',
                'fmin',
                'fmax',
                'strand'
            ).filter(feature__in=gene_ids))
            gene_loc_map = dict((o.feature_id, o) for o in gene_locs)

            # construct a list of genes for each track
            for key in tracks.keys():
                chromosome_id, lower_bound, upper_bound = key
                for o in gene_pool:
                    if o.chromosome_id == chromosome_id and o.number >= lower_bound\
                    and o.number <= upper_bound:
                        tracks[key].append(o)
                tracks[key] = map(
                    lambda x: x.gene_id,
                    sorted(tracks[key], key=lambda o: o.number)
                )

        # jsonify the tracks... that's right, jsonify
        groups = []
        y = 1
        for key in tracks.keys():
            chromosome_id, lower_order, upper_order = key
            gene_json = []
            for g in tracks[key]:
                family = track_family_map[g] if g in track_family_map else ''
                gene_json.append('{"name":"' + gene_name_map[g] + '", "id":' +
                    str(g) + ', "family":"' +family + '", "fmin":' +
                    str(gene_loc_map[g].fmin) + ', "fmax":' +
                    str(gene_loc_map[g].fmax) + ', "strand":' +
                    str(gene_loc_map[g].strand)+'}')
            o = id_organism_map[id_chromosome_map[chromosome_id].organism_id]
            group = ('{"genus":"' + o.genus +
                '", "species":"' + o.species +
                '", "species_id":' +
                str(id_chromosome_map[chromosome_id].organism_id) +
                ', "chromosome_name":"' + id_chromosome_map[chromosome_id].name +
                '", "chromosome_id":' + str(chromosome_id) + ', "genes":[' +
                ','.join(gene_json)+']}')
            groups.append(group)
            # prepare for the next track
            y += 1

        ################
        # begin - json #
        ################

        # make the family json
        family_json = []
        for f in family_ids :
            family_json.append('{"name":"'+f+'", "id":"'+f+'"}')
        view_json = '{"families":['+','.join(family_json)+'], "groups":['

        # make the final json
        view_json += ','.join(groups)+']}'

        return HttpResponse(
            json.dumps(view_json),
            content_type='application/json; charset=utf8'
        )
    return HttpResponseBadRequest()


# returns all the GENES for the given chromosome that have the same family as
# the query
@csrf_exempt
@ensure_nocache
def v1_global_plot(request):
    # parse the POST data (Angular puts it in the request body)
    POST = json.loads(request.body)

    # make sure the request type is POST and that it contains a query (families)
    if request.method == 'POST' and 'query' in POST and 'chromosome' in POST:
        # get the gene family type
        gene_family_type = list(Cvterm.objects.only('pk')\
            .filter(name='gene family'))
        if len(gene_family_type) == 0:
            raise Http404
        gene_family_type = gene_family_type[0]

        # find all genes with the same families
        chromosome_gene_orders = GeneOrder.objects.filter(
            chromosome=POST["chromosome"]
        )
        chromosome_gene_ids = chromosome_gene_orders.values_list(
            "gene", flat=True
        )
        related_genes = Featureprop.objects.only('feature').filter(
            type=gene_family_type,
            value__in=POST['query'],
            feature__in=chromosome_gene_ids
        )
        gene_family_map = dict((o.feature_id, o.value) for o in related_genes)
        related_gene_ids = gene_family_map.keys()

        # get all the gene names
        gene_names = Feature.objects.only('name').filter(
            pk__in=related_gene_ids
        )
        gene_name_map = dict((o.pk, o.name) for o in gene_names)

        # get all the gene featurelocs
        gene_locs = Featureloc.objects.only('fmin', 'fmax', 'strand')\
            .filter(feature__in=related_gene_ids)
        gene_loc_map = dict((o.feature_id, o) for o in gene_locs)

        # make the json
        gene_json = []
        for g in related_gene_ids:
            loc = gene_loc_map[g]
            gene_json.append({
                "name": gene_name_map[g],
                "id": g,
                "family": str(gene_family_map[g]),
                "fmin": loc.fmin,
                "fmax": loc.fmax,
                "strand": loc.strand,
                "x": 0,
                "y": 0
            })
        # return the plot data as encoded as json
        return HttpResponse(
            json.dumps(gene_json),
            content_type='application/json; charset=utf8'
        )
    return HttpResponseBadRequest()


# returns chromosome scale synteny blocks for the chromosome of the given gene
@csrf_exempt
@ensure_nocache
def v1_macro_synteny(request):
    # parse the POST data (Angular puts it in the request body)
    POST = json.loads(request.body)
    # make sure the request type is POST and that it contains a query (families)
    if request.method == 'POST' and 'chromosome' in POST:
        # get the query chromosome
        chromosome = get_object_or_404(Feature, name=POST['chromosome'])
        # get the syntenic region cvterm
        synteny_type = list(Cvterm.objects.only('pk')\
            .filter(name='syntenic_region'))
        if len(synteny_type) == 0:
            raise Http404
        synteny_type = synteny_type[0]
        # get all the related featurelocs
        blocks = list(Featureloc.objects\
            .only('feature', 'fmin', 'fmax', 'strand')\
            .filter(srcfeature=chromosome, feature__type=synteny_type, rank=0))
        # get the chromosome each region belongs to
        region_ids = map(lambda b: b.feature_id, blocks)
        regions = None
        if 'results' in POST:
            regions = list(Featureloc.objects\
                .only('feature', 'srcfeature')\
                .filter(feature__in=region_ids, srcfeature__in=POST['results'], rank=1))
        else:
            regions = list(Featureloc.objects\
                .only('feature', 'srcfeature')\
                .filter(feature__in=region_ids, rank=1))
        region_to_chromosome = dict(
            (r.feature_id, r.srcfeature_id) for r in regions
        )
        # actually get the chromosomes
        chromosomes = list(Feature.objects.only('name', 'organism')\
            .filter(pk__in=region_to_chromosome.values()))
        chromosome_map = dict((c.pk, c) for c in chromosomes)
        # get the chromosomes' organisms
        organisms = Organism.objects.only('genus', 'species').filter(
            pk__in=map(lambda c: c.organism_id, chromosomes)
        )
        organism_map = dict((o.pk, o) for o in organisms)
        # group the blocks by feature
        feature_locs = {}
        for l in blocks:
            if l.feature_id in region_to_chromosome:
                orientation = '-' if l.strand == -1 else '+'
                c = chromosome_map[region_to_chromosome[l.feature_id]]
                name = c.name
                o = organism_map[c.organism_id]
                species = o.species
                genus = o.genus
                feature_locs.setdefault((name, species, genus), []).append(
                    {'start':l.fmin, 'stop':l.fmax, 'orientation':orientation}
                )
        # generate the json
        tracks = []
        for (name, species, genus), blocks in feature_locs.iteritems():
            tracks.append({
                'chromosome': name,
                'species': species,
                'genus': genus,
                'blocks': blocks
            })
        synteny_json = {'chromosome': chromosome.name,
                        'length': chromosome.seqlen,
                        'tracks': tracks}
        # return the synteny data as encoded as json
        return HttpResponse(
            json.dumps(synteny_json),
            content_type='application/json; charset=utf8'
        )
    return HttpResponseBadRequest()


# returns the gene on the given chromosome that is closest to the given position
@csrf_exempt
@ensure_nocache
def v1_nearest_gene(request):
    # parse the POST data (Angular puts it in the request body)
    POST = json.loads(request.body)
    # make sure the request type is POST and that it contains the correct data
    if request.method == 'POST' and 'chromosome' in POST and 'position' in POST:
        # parse the position
        pos = POST['position']
        try:
            pos = int(pos)
            if pos < 0:
                raise ValueError("matched can't be negative")
        except:
            return HttpResponseBadRequest()
        # get the gene type
        sequence_cv = Cv.objects.only('pk').filter(name='sequence')
        gene_type = list(
            Cvterm.objects.only('pk').filter(name='gene', cv_id=sequence_cv)
        )
        if len(gene_type) == 0:
            raise Http404
        gene_type = gene_type[0]
        # find the gene closest to the given position
        loc = Featureloc.objects.only(
            'feature_id',
            'srcfeature_id',
            'fmin',
            'fmax',
            'strand'
        ).filter(
            feature__type=gene_type, srcfeature=POST['chromosome']
        ).annotate(dist=Func(
            ((F('fmin') + F('fmax')) / 2) - pos, function='ABS'
        )).order_by('dist').first()
        gene = get_object_or_404(Feature, pk=loc.feature.pk)
        family = None
        try:
            family = GeneFamilyAssignment.objects.get(gene_id=gene.pk)
        except GeneFamilyAssignment.DoesNotExist:
            family = GeneFamilyAssignment(family_label='')
        # jsonify the gene and return it
        data = {
            "name": gene.name,
            "id": gene.pk,
            "family": family.family_label,
            "fmin": loc.fmin,
            "fmax": loc.fmax,
            "strand": loc.strand
        }
        # return the synteny data as encoded as json
        return HttpResponse(
            json.dumps(data),
            content_type='application/json; charset=utf8'
        )
    return HttpResponseBadRequest()

###############
# depreciated #
###############

# returns contexts centered at genes in the list provided
@csrf_exempt
@ensure_nocache
def micro_synteny_basic(request):
    # parse the POST data (Angular puts it in the request body)
    POST = json.loads(request.body)

    # make sure the request type is POST and that it contains a list of genes
    if request.method == 'POST' and 'genes' in POST and 'numNeighbors' in POST:
        POST['neighbors'] = POST['numNeighbors']
        del POST['numNeighbors']
        request._body = json.dumps(POST)
        return v1_micro_synteny_basic(request)
    return HttpResponseBadRequest()


# resolves a focus gene name to a query track
@csrf_exempt
@ensure_nocache
def gene_to_query(request):
    # parse the POST data (Angular puts it in the request body)
    POST = json.loads(request.body)

    # make sure the request type is POST and that it contains a focus gene name
    if request.method == 'POST' and 'gene' in POST and 'numNeighbors' in POST:
        POST['neighbors'] = POST['numNeighbors']
        del POST['numNeighbors']
        request._body = json.dumps(POST)
        return v1_gene_to_query_track(request)
    return HttpResponseBadRequest()


# returns similar contexts to the families provided
@csrf_exempt
@ensure_nocache
def micro_synteny_search(request):
    # parse the POST data (Angular puts it in the request body)
    POST = json.loads(request.body)

    # make sure the request type is POST and that it contains a query (families)
    if request.method == 'POST' and 'query' in POST and 'numNeighbors' in POST and 'numMatchedFamilies' in POST:
        POST['matched'] = POST['numMatchedFamilies']
        del POST['numMatchedFamilies']
        POST['intermediate'] = POST['numNonFamily']
        del POST['numNonFamily']
        request._body = json.dumps(POST)
        return v1_micro_synteny_search(request)
    return HttpResponseBadRequest()


# returns all the GENES for the given chromosome that have the same family as
# the query
@csrf_exempt
@ensure_nocache
def global_plots(request):
    # parse the POST data (Angular puts it in the request body)
    POST = json.loads(request.body)

    # make sure the request type is POST and that it contains a query (families)
    if request.method == 'POST' and 'query' in POST and 'chromosomeID' in POST:
        POST['chromosome'] = POST['chromosomeID']
        del POST['chromosomeID']
        request._body = json.dumps(POST)
        return v1_global_plot(request)
    return HttpResponseBadRequest()


########
# v1.1 #
########


# returns the requested chromosome (ordered list of gene families)
@csrf_exempt
@ensure_nocache
def v1_1_chromosome(request):
    # parse the POST data (Angular puts it in the request body)
    POST = json.loads(request.body)
    # make sure the request type is POST and that it contains a query (families)
    if request.method == 'POST' and 'chromosome' in POST and 'species_id' in POST:
        # get the query chromosome
        chromosome = get_object_or_404(Feature, name=POST['chromosome'], organism_id=POST['species_id'])

        # get all the genes on the query chromosomes
        genes = list(GeneOrder.objects.only(
            'gene_id',
            'number',
            'chromosome_id'
        ).filter(chromosome=chromosome)
         .order_by('number')
         .values_list('gene_id', flat=True))

        gene_names = list(Feature.objects.only('name').filter(
          feature_id__in=genes))
        gene_name_map = dict((g.pk, g.name) for g in gene_names)

        # get the genomic locations of the genes
        flocs = list(Featureloc.objects.only(
            'feature_id',
            'fmin',
            'fmax',
            'strand'
        ).filter(feature__in=genes))
        gene_loc_map = dict((f.feature_id, {'fmin': f.fmin, 'fmax': f.fmax})
            for f in flocs)

        # get all the families on the query chromosome
        gene_families = list(GeneFamilyAssignment.objects.only(
            'gene_id',
            'family_label'
        ).filter(gene__in=genes))
        gene_family_map = dict((o.gene_id, o.family_label) for o in gene_families)

        # create an ordered list of gene families
        ordered_names    = []
        ordered_locs     = []
        ordered_families = []
        for g_id in genes:
            ordered_names.append(gene_name_map[g_id])
            ordered_locs.append(gene_loc_map[g_id])
            ordered_families.append(gene_family_map.get(g_id, ''))

        # return the chromosome as encoded as json
        output_json = {
            'genes':     ordered_names,
            'locations': ordered_locs,
            'families':  ordered_families,
            'length':    chromosome.seqlen
        }
        return HttpResponse(
            json.dumps(output_json),
            content_type='application/json; charset=utf8'
        )
    return HttpResponseBadRequest()


def macro_synteny_traceback(path_ends, pointers, scores, minsize):
  path_ends.sort(reverse=True)
  for _, end in path_ends:
    if end in pointers:  # note: singletons aren't in pointers
      if scores[end] < minsize:
        break
      begin = end
      while begin in pointers:
        begin = pointers.pop(begin)
      length = scores[end] - scores[begin]
      if length >= minsize:
        yield (begin, end)


def macro_synteny_paths(((c_id, chromosome), (family_num_map, trivial_blocks, maxinsert,
minsize, familymask, chromosome_as_genes, family_counts))):
  # generate number pairs ORDERED BY CHROMOSOME GENE NUMBER THEN QUERY
  # GENE NUMBER - this is a topological sorting
  pairs = []
  for i in range(len(chromosome)):
    f = chromosome[i]
    if f in family_num_map and family_counts[f] <= familymask:
      nums = family_num_map[f]
      pairs.extend(map(lambda n: (i, n), nums))

  # "construct" a DAG and compute longest paths using a recurrence
  # relation similar to that of DAGchainer
  f_path_ends = []  # orders path end nodes longest to shortest
  f_pointers  = {}  # points to the previous node (pair) in a path
  f_scores    = {}  # the length of the longest path ending at each node
  r_path_ends = []
  r_pointers  = {}
  r_scores    = {}
  # iterate nodes, which are in DAG order
  for i in range(len(pairs)):
    n1, n2 = p1 = pairs[i]
    f_scores[p1] = r_scores[p1] = 1
    dist = float('inf')
    # iterate preceding nodes in DAG from closest to furtherest
    for j in reversed(range(i)):
      m1, m2 = p2 = pairs[j]
      if n1 == m1:
        continue
      # the query and chromosome must agree on the ordering
      # n1 <= m1 is always true
      d1 = n1 - m1
      # forward blocks
      if m2 < n2:
        d2 = n2 - m2
        # are the nodes close enough to be in the same path?
        if d1 <= maxinsert and d2 <= maxinsert:
          s = f_scores[p2] + 1
          d = math.sqrt(math.pow(d1, 2) + math.pow(d2, 2))
          if s > f_scores[p1] or (s == f_scores[p1] and d < dist):
            f_scores[p1]   = s
            f_pointers[p1] = p2
            dist           = d
      # reverse blocks
      if m2 > n2:
        d2 = m2 - n2
        # are the nodes close enough to be in the same path?
        if d1 <= maxinsert and d2 <= maxinsert:
          s = r_scores[p2] + 1
          d = math.sqrt(math.pow(d1, 2) + math.pow(d2, 2))
          if s > r_scores[p1] or (s == f_scores[p1] and d < dist):
            r_scores[p1]   = s
            r_pointers[p1] = p2
            dist           = d
      # if this node is too far away then all remaining nodes are too
      if d1 > maxinsert:
        break
    f_path_ends.append((f_scores[p1], p1))
    r_path_ends.append((r_scores[p1], p1))
  # traceback longest paths and get endpoints
  f = macro_synteny_traceback(f_path_ends, f_pointers, f_scores, minsize)
  r = macro_synteny_traceback(r_path_ends, r_pointers, r_scores, minsize)
  paths     = []
  end_genes = []
  trivial_catcher = []
  for block in chain(f, r):
    if block in trivial_blocks:
      trivial_catcher.append(block)
    else:
      begin, end = block
      paths.append((begin, end))
      end_genes.append(chromosome_as_genes[begin[0]])
      end_genes.append(chromosome_as_genes[end[0]])
  if len(trivial_catcher) != len(trivial_blocks):
    for begin, end in trivial_catcher:
      paths.append((begin, end))
      end_genes.append(chromosome_as_genes[begin[0]])
      end_genes.append(chromosome_as_genes[end[0]])
  return (c_id, paths, end_genes)


# computes chromosome scale synteny blocks for the given chromosome (ordered
# list of gene families)
import time
@csrf_exempt
@ensure_nocache
def v1_1_macro_synteny(request):
    global CHROMOSOME_FAMILY_COUNTS, CHROMOSOME_MAP, CHROMOSOMES_AS_FAMILIES,\
        CHROMOSOMES_AS_GENES
    # parse the POST data (Angular puts it in the request body)
    POST = json.loads(request.body)
    # make sure the request type is POST and that it contains a query (families)
    if request.method == 'POST' and 'families' in POST and 'matched' in POST and\
    'intermediate' in POST and 'mask' in POST:
        pool = ThreadPool(4)

        T0 = t0 = time.time()
        # parse the parameters
        query      = POST['families']
        maxinsert  = POST['intermediate'] + 1
        minsize    = POST['matched'] + 1
        familymask = POST['mask']

        # make a dictionary that maps families to query gene numbers
        family_num_map = defaultdict(list)
        self_matches = OrderedDict()
        mask = set()
        for i in range(len(query)):
          f = query[i]
          if f != '':
            self_matches[i] = None
            family_num_map[f].append(i)
            if len(family_num_map[f]) > familymask:
                mask.add(f)
        # remove families that have too many members
        for f in mask:
          for i in family_num_map[f]:
            del self_matches[i]
          del family_num_map[f]
        # compute all trivial self comparison blocks
        trivial_blocks = set()
        begin, _ = self_matches.popitem(last=False)
        end = begin
        for i in self_matches:
          if i - end > maxinsert:
            if end - begin >= minsize:
              block = ((begin, begin), (end, end))
              trivial_blocks.add(block)
            begin = i
          end = i
        if end - begin >= minsize:
          block = ((begin, begin), (end, end))
          trivial_blocks.add(block)

        t1 = time.time()
        total = t1-t0
        print "filtering: " + str(total)
        T1 = t0 = t1

        # mine synteny from each chromosome
        args = []
        for c_id in CHROMOSOMES_AS_FAMILIES:
          genes = CHROMOSOMES_AS_GENES[c_id]
          counts = CHROMOSOME_FAMILY_COUNTS[c_id]
          c_args = (family_num_map, trivial_blocks, maxinsert, minsize, familymask, genes, counts)
          args.append(c_args)
        data = zip(CHROMOSOMES_AS_FAMILIES.iteritems(), args)
        results = pool.map(macro_synteny_paths, data)
        paths     = {}
        end_genes = []
        for c_id, c_paths, c_end_genes in results:
            if c_paths:
                paths[c_id] = c_paths
                end_genes.extend(c_end_genes)

        t1 = time.time()
        total = t1-T1
        print "algorithm: " + str(total)
        t0 = t1

        # get the genomic locations of the genes that each path begin/ends at
        flocs = list(Featureloc.objects.only(
            'feature_id',
            'fmin',
            'fmax',
            'strand'
        ).filter(feature__in=end_genes))
        gene_loc_map = dict((f.feature_id, {'fmin': f.fmin, 'fmax': f.fmax})
            for f in flocs)

        # get the organism of each chromosome that has blocks
        organism_ids = map(lambda c: CHROMOSOME_MAP[c].organism_id, paths.keys())
        organisms = list(Organism.objects.only('genus', 'species')
            .filter(pk__in=organism_ids))
        organism_map = dict((o.pk, o) for o in organisms)

        t1 = time.time()
        total = t1-t0
        print "organsisms: " + str(total)
        t0 = t1

        # generate the JSON
        tracks = []
        for c_id, c_paths in paths.iteritems():
            blocks = []
            for begin, end in c_paths:
                begin_gene = CHROMOSOMES_AS_GENES[c_id][begin[0]]
                end_gene   = CHROMOSOMES_AS_GENES[c_id][end[0]]
                begin_loc  = gene_loc_map[begin_gene]
                end_loc    = gene_loc_map[end_gene]
                start      = min(begin_loc['fmin'], begin_loc['fmax'])
                stop       = max(end_loc['fmin'], end_loc['fmax'])
                query_start, query_stop, orientation = (begin[1], end[1], '+') \
                    if begin[1] < end[1] else (end[1], begin[1], '-')
                blocks.append({
                    'query_start': query_start,
                    'query_stop':  query_stop,
                    'start':       start,
                    'stop':        stop,
                    'orientation': orientation
                })
            c = CHROMOSOME_MAP[c_id]
            organism = organism_map[c.organism_id]
            tracks.append({
                'chromosome': c.name,
                'species':    organism.species,
                'genus':      organism.genus,
                'blocks':     blocks
            })

        t1 = time.time()
        total = t1-t0
        print "json: " + str(total)

        total = t1-T0
        print "total: " + str(total)

        pool.close()

        # create and return JSON
        return HttpResponse(
            json.dumps(tracks),
            content_type='application/json; charset=utf8'
        )
    return HttpResponseBadRequest()
