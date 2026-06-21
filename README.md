# segTree

O SegTree é uma ferramenta geoespacial desenvolvida para automatizar o mapeamento e o inventário da arborização urbana. O plugin processa dados altimétricos tridimensionais de alta densidade, aplicando um pipeline sequencial otimizado que inclui: ordenação geométrica pela componente Z, translação posicional dinâmica, filtragem estatística de ruídos por densidade de voxel e um laço computacional de agrupamento baseado em critérios de distância 3D e Casco Convexo (Convex Hull).

Projetado para o ecossistema do QGIS, o SegTree substitui dependências espaciais externas por algoritmos nativos da API QgsGeometry, garantindo interoperabilidade, conformidade com padrões geoespaciais e alta performance na extração automatizada de copas individuais. 

Considere a instalação das dependências: "python -m pip install open3d numpy scipy alphashape"

## About
Segmentador automatizado de nuvem de pontos tridimensionais (LiDAR/Fotogrametria) com foco em inventário florestal e individualização de copas de árvores urbanas, utilizando a API de geometria nativa do QGIS.

## Author
Lucas Jamiro Barbosa <eng.lucasjb@outlook.com>

## Repository
- Homepage: 
- Repository: 
- Tracker: 
