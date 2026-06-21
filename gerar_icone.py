import os
import matplotlib.pyplot as plt

# Cria o gráfico no tamanho exato de ícones do QGIS (32x32 pixels com DPI baixo)
fig, ax = plt.subplots(figsize=(0.32, 0.32), dpi=100)

# 1. Desenha o Tronco da Árvore (Marrom Estilizado)
ax.plot([0, 0], [-0.7, -0.1], color='#5c4033', linewidth=3, solid_capstyle='round')

# 2. Desenha a Copa da Árvore como uma malha geométrica de triângulos (Representando o Casco Convexo/LiDAR)
# Triângulo da Esquerda (Azul Geoespacial)
ax.fill([-0.7, 0, 0], [-0.1, 0.7, -0.1], color='#0033aa', alpha=0.8)
# Triângulo da Direita (Verde Nuvem de Pontos)
ax.fill([0, 0, 0.7], [-0.1, 0.7, -0.1], color='#00ff66', alpha=0.9)

# 3. Adiciona pontos flutuantes simulando os pontos LiDAR
ax.scatter([-0.3, 0.3, 0.0, -0.1, 0.2], [0.1, 0.2, 0.5, 0.3, 0.0], color='#ffffff', s=1.5, zorder=4)

# Configurações rígidas de limites e fundo invisível para o Qt6
ax.set_xlim(-1, 1)
ax.set_ylim(-1, 1)
ax.axis('off')
fig.patch.set_facecolor('none')
ax.set_facecolor('none')

# Força o salvamento como PNG puro de 32x32 sem bordas
caminho_salvamento = os.path.join(os.path.dirname(__file__), 'icon.png')
plt.savefig(caminho_salvamento, bbox_inches='tight', pad_inches=0, transparent=True)
plt.close()

print(f"Novo ícone de alta compatibilidade gerado em: {caminho_salvamento}")