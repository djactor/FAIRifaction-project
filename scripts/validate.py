from pathlib import Path

from pyshacl import validate
from rdflib import Graph

ROOT = Path(__file__).resolve().parent.parent


def load(*paths):
    g = Graph()
    for p in paths:
        g.parse(ROOT / p, format="turtle")
    return g


def check(title, data, shapes, ont=None):
    conforms, _, text = validate(data, shacl_graph=shapes, ont_graph=ont, inference="rdfs",
                                 allow_warnings=True, abort_on_first=False)
    print(f"{'PASS' if conforms else 'FAIL'}  {title}")
    if not conforms:
        print(text)
    return conforms


def main():
    ok = True
    ontology = load("ontology/benelux-population-ontology.ttl")
    ok &= check("RDF data conforms to the data shapes",
                load("data/rdf/benelux-city-population.ttl"),
                load("shapes/population-data-shape.ttl"), ontology)

    schemas = load("metadata/schemas/dataset-schema.ttl", "metadata/schemas/distribution-schema.ttl",
                   "shapes/fdp-resource-shape-reference.ttl")
    for record in ("dataset.ttl", "distribution-original-csv.ttl", "distribution-rdf-turtle.ttl"):
        ok &= check(f"metadata record {record} conforms to the metadata schemas",
                    load(f"metadata/records/{record}"), schemas)

    for f in ("data/original/Benelux_data.csv", "data/rdf/benelux-city-population.ttl"):
        print(f"byteSize of {f}: {(ROOT / f).stat().st_size}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
