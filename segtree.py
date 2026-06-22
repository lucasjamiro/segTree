# -*- coding: utf-8 -*-
"""
/***************************************************************************
 SegTree - QGIS 4 Plugin (PyQt6)
 Segmentador de nuvem de pontos, com foco em individualização de árvores urbanas.
 Desenvolvido utilizando a API nativa de Geometria do QGIS.
 ***************************************************************************/
"""

import os
import time
from collections import Counter

# Componentes do QGIS 4 (Baseados rigorosamente no PyQt6)
from qgis.PyQt import uic, QtWidgets
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox, QButtonGroup # QButtonGroup fica em QtWidgets no PyQt6!
from qgis.PyQt.QtGui import QAction, QIcon # QAction e QIcon ficam em QtGui no PyQt6!
from qgis.core import QgsGeometry, QgsPointXY

# Bloco de proteção para importações científicas pesadas essenciais
try:
    import numpy as np
    import open3d as o3d
    from scipy.spatial import ConvexHull
    BIBLIOTECAS_OK = True
except ImportError as e:
    BIBLIOTECAS_OK = False
    BIBLIOTECA_FALTANTE = str(e).split("'")[-2] if "'" in str(e) else "dependências"


# =====================================================================
# LOCALIZADOR DINÂMICO DO ARQUIVO DE INTERFACE (.UI) NA SUBPASTA 'UI'
# =====================================================================
PASTA_PRINCIPAL = os.path.dirname(__file__)
# Aponta diretamente para a subpasta onde o arquivo está guardado
PASTA_UI = os.path.join(PASTA_PRINCIPAL, 'ui')
ARQUIVO_UI = None

# Verifica se a subpasta 'ui' realmente existe antes de varrer
if os.path.exists(PASTA_UI):
    for arquivo_na_pasta in os.listdir(PASTA_UI):
        if arquivo_na_pasta.lower().endswith('.ui'):
            ARQUIVO_UI = os.path.join(PASTA_UI, arquivo_na_pasta)
            break

# Se não encontrou na subpasta, tenta procurar na pasta raiz como plano B
if ARQUIVO_UI is None:
    for arquivo_na_pasta in os.listdir(PASTA_PRINCIPAL):
        if arquivo_na_pasta.lower().endswith('.ui'):
            ARQUIVO_UI = os.path.join(PASTA_PRINCIPAL, arquivo_na_pasta)
            break

# Se mesmo assim não achar em lugar nenhum, avisa o usuário de forma limpa
if ARQUIVO_UI is None:
    raise FileNotFoundError(f"Erro Crítico: Nenhum arquivo .ui foi encontrado na pasta principal ou na subpasta 'ui'.")

# Carrega a interface encontrada de forma nativa no QGIS 4 / PyQt6
FORM_CLASS, _ = uic.loadUiType(ARQUIVO_UI)


# =====================================================================
# CLASSE DA INTERFACE GRÁFICA (Baseada no FORM_CLASS do arquivo .ui)
# =====================================================================
class SegTreeDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, iface, parent=None):
        """Construtor da Janela do Plugin."""
        super(SegTreeDialog, self).__init__(parent)
        self.setupUi(self)
        
        # Guarda o controle do QGIS de forma isolada
        self.iface = iface 
        
        # Variáveis globais da memória do diálogo
        self.point_cloud_translated = None  
        self.all_points = None              
        self.all_colors = None              
        self.segments = None                
        self.minimoX = 0.0
        self.minimoY = 0.0

        # =====================================================================
        # CONEXÃO MANUAL FORÇA BRUTA DOS BOTÕES OK E CANCELAR (CORREÇÃO DE TRAVA)
        # =====================================================================
        if hasattr(self, 'buttonBox'):
            self.buttonBox.accepted.connect(self.accept) 
            self.buttonBox.rejected.connect(self.reject) 
        else:
            for widget in self.findChildren(QtWidgets.QDialogButtonBox):
                widget.accepted.connect(self.accept)
                widget.rejected.connect(self.reject)
                break

        # --- VERIFICAÇÃO DE SEGURANÇA DE DEPENDÊNCIAS ---
        if not BIBLIOTECAS_OK:
            QMessageBox.critical(
                self, "Erro de Dependência", 
                f"A biblioteca espacial '{BIBLIOTECA_FALTANTE}' não está instalada no Python deste QGIS.\n\n"
                "Por favor, abra o 'OSGeo4W Shell' como Administrador e execute:\n"
                "python -m pip install open3d numpy scipy"
            )

        # Configuração da Aba 1: Normalização (Exclusividade de CheckBoxes)
        self.grupo_normalizacao = QButtonGroup(self)
        self.grupo_normalizacao.addButton(self.checkBox_yesNormalized)
        self.grupo_normalizacao.addButton(self.checkBox_noNormalized)
        self.grupo_normalizacao.setExclusive(True)
        self.checkBox_yesNormalized.setChecked(True)

        # Conexões dos botões da Aba 1
        self.pushButton_loadFile_Vegetation.clicked.connect(self.carregar_arquivo_vegetacao)
        self.pushButton_loadFile_Ground.clicked.connect(self.carregar_arquivo_terreno)
        self.pushButton_readFiles.clicked.connect(self.etapa1_ler_e_transladar)
        self.pushButton_runNormalization.clicked.connect(self.executar_normalizacao)
        
        self.checkBox_yesNormalized.toggled.connect(self.atualizar_estado_widgets_aba1)
        self.checkBox_noNormalized.toggled.connect(self.atualizar_estado_widgets_aba1)
        
        # Configuração da Aba 2: Filtragem Voxel
        self.grupo_filtragem = QButtonGroup(self)
        self.grupo_filtragem.addButton(self.checkBox_yesFiltering)
        self.grupo_filtragem.addButton(self.checkBox_noFiltering)
        self.grupo_filtragem.setExclusive(True)
        self.checkBox_yesFiltering.setChecked(True)

        self.checkBox_yesFiltering.toggled.connect(self.atualizar_estado_widgets_aba2)
        self.checkBox_noFiltering.toggled.connect(self.atualizar_estado_widgets_aba2)
        
        # --- CONEXÃO DA ABA 2 (FILTRAGEM VOXEL) COM TRAVA DE SEGURANÇA ---
        # Tenta conectar usando o nome provável do botão no QGIS 4, se não, usa o genérico
        if hasattr(self, 'pushButton_runFiltering'):
            self.pushButton_runFiltering.clicked.connect(self.etapa2_filtragem_voxel)
        elif hasattr(self, 'pushButton'):
            self.pushButton.clicked.connect(self.etapa2_filtragem_voxel)
        else:
            # Caso o botão tenha outro nome no seu Qt Designer (ex: pushButton_filtrar)
            # Vamos varrer a interface para achar o botão da etapa 2 dinamicamente
            botao_encontrado = False
            for widget in self.findChildren(QtWidgets.QPushButton):
                if "filter" in widget.objectName().lower() or "filtrar" in widget.objectName().lower():
                    widget.clicked.connect(self.etapa2_filtragem_voxel)
                    botao_encontrado = True
                    break
            # Plano C: Se não achou por nome nenhum, conecta o genérico que existir na aba 2
            if not botao_encontrado and hasattr(self, 'pushButton'):
                self.pushButton.clicked.connect(self.etapa2_filtragem_voxel)
        self.pushButton_runSegmentation.clicked.connect(self.etapa3_executar_segmentacao)

        # Valores padrões da interface
        self.lineEdit_voxelSize.setText("1.0")
        self.lineEdit_pointsPerVoxel.setText("2")
        self.lineEdit_distance.setText("1.0")
        self.lineEdit_buffer.setText("1.0")
        self.lineEdit_overlayer.setText("25") # <-- Adicionado: Sugestão inicial de 25%
        
        # Inicialização dos estados visuais
        self.atualizar_estado_widgets_aba1()
        self.atualizar_estado_widgets_aba2()

    def atualizar_estado_widgets_aba1(self):
        precisa_de_terreno = self.checkBox_noNormalized.isChecked()
        self.lineEdit_pathFile_Ground.setEnabled(precisa_de_terreno)
        self.pushButton_loadFile_Ground.setEnabled(precisa_de_terreno)
        self.pushButton_runNormalization.setEnabled(precisa_de_terreno)

    def atualizar_estado_widgets_aba2(self):
        # Verifica se o usuário escolheu "Sim" para filtragem
        filtragem_ativa = self.checkBox_yesFiltering.isChecked()
        
        # Liga/Desliga os campos de texto
        self.lineEdit_pointsPerVoxel.setEnabled(filtragem_ativa)
        self.lineEdit_voxelSize.setEnabled(filtragem_ativa)
        
        # --- NOVA LÓGICA: Liga/Desliga o botão da Etapa 2 ---
        # Procura qual nome de botão está sendo usado na interface e aplica o estado
        if hasattr(self, 'pushButton_runFiltering'):
            self.pushButton_runFiltering.setEnabled(filtragem_ativa)
        elif hasattr(self, 'pushButton'):
            self.pushButton.setEnabled(filtragem_ativa)
        else:
            # Caso tenha sido conectado pelo localizador dinâmico de strings (Plano B)
            for widget in self.findChildren(QtWidgets.QPushButton):
                if "filter" in widget.objectName().lower() or "filtrar" in widget.objectName().lower():
                    widget.setEnabled(filtragem_ativa)
                    break

    def carregar_arquivo_vegetacao(self):
        arquivo, _ = QFileDialog.getOpenFileName(
            self, "Selecionar Nuvem de Pontos (Vegetação)", "", "Nuvens de Pontos (*.las *.laz *.txt);;Todos os arquivos (*.*)"
        )
        if arquivo:
            self.lineEdit_pathFile_Vegetation.setText(arquivo)

    def carregar_arquivo_terreno(self):
        arquivo, _ = QFileDialog.getOpenFileName(
            self, "Selecionar Nuvem de Pontos (Terreno)", "", "Nuvens de Pontos (*.las *.laz *.txt);;Todos os arquivos (*.*)"
        )
        if arquivo:
            self.lineEdit_pathFile_Ground.setText(arquivo)

    def executar_normalizacao(self):
        QMessageBox.information(self, "Normalização", "Aqui entrará o processamento de normalização contra o MNT.")

    def etapa1_ler_e_transladar(self):
        file_path_veg = self.lineEdit_pathFile_Vegetation.text().strip()
        file_path_ground = self.lineEdit_pathFile_Ground.text().strip()

        if not file_path_veg or not os.path.exists(file_path_veg):
            QMessageBox.warning(self, "Arquivo não encontrado", "Por favor, selecione pelo menos o arquivo principal (Vegetação/Único).")
            return

        arquivo_unico_classificado = True if not file_path_ground else False

        # --- CRIAÇÃO DA BARRA DE PROGRESSO NATIVA NA BARRA DE STATUS DO QGIS 4 ---
        status_bar = self.iface.mainWindow().statusBar()
        progresso_qgis = QtWidgets.QProgressBar()
        progresso_qgis.setMaximumWidth(200)
        status_bar.addWidget(progresso_qgis)
        status_bar.showMessage("SegTree | Lendo arquivos LiDAR...")
        progresso_qgis.setValue(10)
        QtWidgets.QApplication.processEvents()

        try:
            # --- CENÁRIO A: ARQUIVO ÚNICO CLASSIFICADO (.LAS / .LAZ) ---
            if arquivo_unico_classificado:
                _, ext = os.path.splitext(file_path_veg.lower())
                if ext not in ['.las', '.laz']:
                    status_bar.removeWidget(progresso_qgis)
                    status_bar.clearMessage()
                    QMessageBox.critical(self, "Formato Inválido", "Para arquivos únicos classificados, selecione um arquivo no formato .las ou .laz.")
                    return
                
                try:
                    import laspy
                except ImportError:
                    status_bar.removeWidget(progresso_qgis)
                    status_bar.clearMessage()
                    QMessageBox.critical(self, "Dependência Faltante", "Instale a biblioteca laspy no console do QGIS para ler as classes:\n\npython -m pip install laspy")
                    return

                las_data = laspy.read(file_path_veg)
                classes = np.asarray(las_data.classification)

                pontos_solo_mask = (classes == 2)
                pontos_veg_mask = np.isin(classes, [3, 4, 5])

                if not np.any(classes != 0) or not np.any(pontos_solo_mask):
                    status_bar.removeWidget(progresso_qgis)
                    status_bar.clearMessage()
                    QMessageBox.critical(
                        self, "Erro de Classificação",
                        "Erro Crítico: A nuvem de pontos selecionada não apresenta classificação de solo/vegetação.\n\n"
                        "O plugin SegTree pressupõe que o arquivo já esteja classificado conforme os padrões da ASPRS."
                    )
                    return

                progresso_qgis.setValue(30)
                QtWidgets.QApplication.processEvents()

                xyz_completo = np.vstack((las_data.x, las_data.y, las_data.z)).T
                dados_vegetacao = xyz_completo[pontos_veg_mask]
                dados_terreno = xyz_completo[pontos_solo_mask]

                if len(dados_vegetacao) == 0 or len(dados_terreno) == 0:
                    status_bar.removeWidget(progresso_qgis)
                    status_bar.clearMessage()
                    QMessageBox.warning(self, "Dados Insuficientes", "Classes ASPRS necessárias (Solo=2, Veg=3,4,5) ausentes ou incompletas.")
                    return

            # --- CENÁRIO B: ARQUIVOS SEPARADOS (.TXT / .XYZ / .LAS) ---
            else:
                if not os.path.exists(file_path_ground):
                    status_bar.removeWidget(progresso_qgis)
                    status_bar.clearMessage()
                    QMessageBox.warning(self, "Arquivo não encontrado", "Caminho do arquivo de terreno inválido.")
                    return
                
                pc_veg = o3d.io.read_point_cloud(file_path_veg)
                progresso_qgis.setValue(25)
                QtWidgets.QApplication.processEvents()
                
                pc_ground = o3d.io.read_point_cloud(file_path_ground)
                progresso_qgis.setValue(35)
                QtWidgets.QApplication.processEvents()
                
                dados_vegetacao = np.asarray(pc_veg.points)
                dados_terreno = np.asarray(pc_ground.points)

            progresso_qgis.setValue(60)
            status_bar.showMessage("SegTree | Transladando coordenadas...")
            QtWidgets.QApplication.processEvents()

            # --- TRANSLADAÇÃO PARA A ORIGEM LOCAL (0,0) ---
            self.minimoX = min(np.min(dados_vegetacao[:, 0]), np.min(dados_terreno[:, 0]))
            self.minimoY = min(np.min(dados_vegetacao[:, 1]), np.min(dados_terreno[:, 1]))

            self.pts_vegetacao_local = np.copy(dados_vegetacao)
            self.pts_vegetacao_local[:, 0] -= self.minimoX
            self.pts_vegetacao_local[:, 1] -= self.minimoY

            self.pts_terreno_local = np.copy(dados_terreno)
            self.pts_terreno_local[:, 0] -= self.minimoX
            self.pts_terreno_local[:, 1] -= self.minimoY

            self.point_cloud_translated = o3d.geometry.PointCloud()
            self.point_cloud_translated.points = o3d.utility.Vector3dVector(self.pts_vegetacao_local)
            self.all_points = np.asarray(self.point_cloud_translated.points)

            # Finaliza a barra de progresso do QGIS de forma limpa
            progresso_qgis.setValue(100)
            status_bar.removeWidget(progresso_qgis)
            status_bar.showMessage("SegTree | Leitura concluída com sucesso!", 5000)

            QMessageBox.information(
                self, "Leitura Concluída",
                f"Nuvem LiDAR carregada com sucesso!\n\n"
                f"Pontos de Vegetação extraídos: {len(self.pts_vegetacao_local)}\n"
                f"Pontos de Solo extraídos: {len(self.pts_terreno_local)}\n"
                f"Dados prontos para o módulo de normalização altimétrica."
            )

        except Exception as e:
            status_bar.removeWidget(progresso_qgis)
            status_bar.clearMessage()
            QMessageBox.critical(self, "Erro na Leitura", f"Falha ao interpretar os dados tridimensionais:\n\n{str(e)}")

    def executar_normalizacao(self):
        """Executa a normalização altimétrica interpolando o solo por planos inclinados (TIN - Delaunay)."""
        if not hasattr(self, 'pts_vegetacao_local') or not hasattr(self, 'pts_terreno_local'):
            QMessageBox.warning(self, "Aviso", "Por favor, execute primeiro a leitura dos arquivos na Aba 1.")
            return

        # --- CRIAR COMPONENTE DE PROGRESSO NA BARRA DE STATUS DO QGIS ---
        status_bar = self.iface.mainWindow().statusBar()
        progresso_normalizacao = QtWidgets.QProgressBar()
        progresso_normalizacao.setMaximumWidth(250)
        status_bar.addWidget(progresso_normalizacao)
        status_bar.showMessage("SegTree | Construindo malha topológica TIN (Delaunay)...")
        
        progresso_normalizacao.setValue(5)
        QtWidgets.QApplication.processEvents()
        start_time = time.time()

        try:
            from scipy.spatial import Delaunay, KDTree
            
            # 1. Constrói a topologia da TIN baseada nos pontos de solo (X, Y)
            triangulacao_solo = Delaunay(self.pts_terreno_local[:, :2])
            progresso_normalizacao.setValue(20)
            QtWidgets.QApplication.processEvents()
            
            # Árvore KD-Tree de backup rápido para pontos fora da borda da TIN
            arvore_solo_backup = KDTree(self.pts_terreno_local[:, :2])
            progresso_normalizacao.setValue(35)
            status_bar.showMessage("SegTree | Mapeando pontos de vegetação na TIN...")
            QtWidgets.QApplication.processEvents()

            vegetacao_normalizada = np.copy(self.pts_vegetacao_local)
            total_veg = len(vegetacao_normalizada)

            # 2. Encontra em qual triângulo da TIN cada ponto de vegetação cai projetado
            indices_triangulos = triangulacao_solo.find_simplex(vegetacao_normalizada[:, :2])
            progresso_normalizacao.setValue(50)
            status_bar.showMessage("SegTree | Calculando equações de planos inclinados...")
            QtWidgets.QApplication.processEvents()

            # 3. Interpolação Linear de plano inclinado tridimensional por triângulo
            for i in range(total_veg):
                if i % max(1, total_veg // 20) == 0:
                    percentual = 50 + int((i / total_veg) * 45) # Vai de 50% a 95%
                    progresso_normalizacao.setValue(percentual)
                    QtWidgets.QApplication.processEvents()

                idx_tri = indices_triangulos[i]
                pt_v = vegetacao_normalizada[i]

                if idx_tri != -1:
                    indices_vertices = triangulacao_solo.simplices[idx_tri]
                    p0 = self.pts_terreno_local[indices_vertices[0]]
                    p1 = self.pts_terreno_local[indices_vertices[1]]
                    p2 = self.pts_terreno_local[indices_vertices[2]]

                    # Equação matemática do plano do triângulo (Z = Ax + By + C)
                    A = np.array([
                        [p0[0], p0[1], 1],
                        [p1[0], p1[1], 1],
                        [p2[0], p2[1], 1]
                    ])
                    B = np.array([p0[2], p1[2], p2[2]])
                    
                    try:
                        coef = np.linalg.solve(A, B)
                        z_solo_interpolado = coef[0] * pt_v[0] + coef[1] * pt_v[1] + coef[2]
                    except np.linalg.LinAlgError:
                        _, idx_solo = arvore_solo_backup.query(pt_v[:2], k=1)
                        z_solo_interpolado = self.pts_terreno_local[idx_solo, 2]
                else:
                    _, idx_solo = arvore_solo_backup.query(pt_v[:2], k=1)
                    z_solo_interpolado = self.pts_terreno_local[idx_solo, 2]

                # Executa a subtração altimétrica da normalização
                vegetacao_normalizada[i, 2] -= z_solo_interpolado

            # Força o piso físico a zero
            vegetacao_normalizada[:, 2] = np.maximum(0.0, vegetacao_normalizada[:, 2])

            # Atualiza os dados na memória global para as próximas etapas
            self.pts_vegetacao_local = vegetacao_normalizada
            self.point_cloud_translated.points = o3d.utility.Vector3dVector(self.pts_vegetacao_local)
            self.all_points = np.asarray(self.point_cloud_translated.points)

            elapsed_time = time.time() - start_time
            
            # Limpa os componentes injetados na barra de status do QGIS
            progresso_normalizacao.setValue(100)
            status_bar.removeWidget(progresso_normalizacao)
            status_bar.showMessage("SegTree | Normalização por TIN finalizada!", 5000)

            QMessageBox.information(
                self, "Normalização por TIN Concluída",
                f"Processamento altimétrico finalizado com sucesso via Triangulação de Delaunay!\n\n"
                f"As alturas (Z) foram corrigidas com base no plano inclinado do relevo local de Curitiba.\n"
                f"Tempo total de processamento: {elapsed_time:.2f} segundos."
            )

        except Exception as e:
            status_bar.removeWidget(progresso_normalizacao)
            status_bar.clearMessage()
            QMessageBox.critical(self, "Falha na Normalização", f"Erro no processamento matemático da TIN:\n\n{str(e)}")

    def executar_normalizacao(self):
        """Executa a normalização altimétrica interpolando o solo por planos inclinados (TIN - Delaunay)."""
        if not hasattr(self, 'pts_vegetacao_local') or not hasattr(self, 'pts_terreno_local'):
            QMessageBox.warning(self, "Aviso", "Por favor, execute primeiro a leitura dos arquivos na Aba 1.")
            return

        QtWidgets.QApplication.processEvents()
        start_time = time.time()

        try:
            from scipy.spatial import Delaunay, KDTree
            
            # 1. Constrói a topologia da TIN baseada nos pontos de solo (X, Y)
            QtWidgets.QApplication.processEvents()
            triangulacao_solo = Delaunay(self.pts_terreno_local[:, :2])
            
            # Árvore KD-Tree de backup rápido para pontos de vegetação que caiam fora da borda da TIN
            arvore_solo_backup = KDTree(self.pts_terreno_local[:, :2])

            QtWidgets.QApplication.processEvents()

            vegetacao_normalizada = np.copy(self.pts_vegetacao_local)
            total_veg = len(vegetacao_normalizada)

            # 2. Encontra em qual triângulo da TIN cada ponto de vegetação cai projetado no plano XY
            # Retorna o índice do triângulo na matriz. Retorna -1 se estiver fora da triangulação.
            indices_triangulos = triangulacao_solo.find_simplex(vegetacao_normalizada[:, :2])

            QtWidgets.QApplication.processEvents()

            # 3. Interpolação Linear de plano inclinado tridimensional por triângulo
            for i in range(total_veg):
                if i % max(1, total_veg // 20) == 0:
                    percentual = 60 + int((i / total_veg) * 35) # Vai de 60% a 95%
                    QtWidgets.QApplication.processEvents()

                idx_tri = indices_triangulos[i]
                pt_v = vegetacao_normalizada[i]

                if idx_tri != -1:
                    # Recupera os 3 vértices (pontos de solo reais) que formam este triângulo específico
                    indices_vertices = triangulacao_solo.simplices[idx_tri]
                    p0 = self.pts_terreno_local[indices_vertices[0]]
                    p1 = self.pts_terreno_local[indices_vertices[1]]
                    p2 = self.pts_terreno_local[indices_vertices[2]]

                    # Equação matemática do plano do triângulo (Matriz de determinantes)
                    # Resolve o sistema linear Z = Ax + By + C para encontrar a cota exata do terreno abaixo de pt_v
                    A = np.array([
                        [p0[0], p0[1], 1],
                        [p1[0], p1[1], 1],
                        [p2[0], p2[1], 1]
                    ])
                    B = np.array([p0[2], p1[2], p2[2]])
                    
                    try:
                        coef = np.linalg.solve(A, B)
                        z_solo_interpolado = coef[0] * pt_v[0] + coef[1] * pt_v[1] + coef[2]
                    except np.linalg.LinAlgError:
                        # Fallback seguro caso o triângulo seja degenerado (área zero)
                        _, idx_solo = arvore_solo_backup.query(pt_v[:2], k=1)
                        z_solo_interpolado = self.pts_terreno_local[idx_solo, 2]
                else:
                    # FALLBACK DE BORDA: Se o ponto de vegetação estiver fora do perímetro da TIN
                    # ele usa a cota do ponto de solo mais próximo via vizinhança direta
                    _, idx_solo = arvore_solo_backup.query(pt_v[:2], k=1)
                    z_solo_interpolado = self.pts_terreno_local[idx_solo, 2]

                # Executa a subtração altimétrica da normalização (H = Z_absoluto_veg - Z_terreno_inclinado)
                vegetacao_normalizada[i, 2] -= z_solo_interpolado

            # Força o piso físico a zero (evita micro-valores negativos causados por folhas abaixo da TIN)
            vegetacao_normalizada[:, 2] = np.maximum(0.0, vegetacao_normalizada[:, 2])

            # Atualiza os dados na memória global para as próximas etapas
            self.pts_vegetacao_local = vegetacao_normalizada
            self.point_cloud_translated.points = o3d.utility.Vector3dVector(self.pts_vegetacao_local)
            self.all_points = np.asarray(self.point_cloud_translated.points)

            elapsed_time = time.time() - start_time

            QMessageBox.information(
                self, "Normalização por TIN Concluída",
                f"Processamento altimétrico finalizado com sucesso via Triangulação de Delaunay!\n\n"
                f"As alturas (Z) foram corrigidas com base no plano inclinado do relevo local de Curitiba.\n"
                f"Tempo total de processamento: {elapsed_time:.2f} segundos."
            )

        except Exception as e:
            QMessageBox.critical(self, "Falha na Normalização", f"Erro no processamento matemático da TIN:\n\n{str(e)}")
    def etapa2_filtragem_voxel(self):
        if self.point_cloud_translated is None:
            QMessageBox.warning(self, "Aviso", "Por favor, execute primeiro a Etapa 1 na Aba 1.")
            return

        if self.checkBox_noFiltering.isChecked():
            self.all_points = np.asarray(self.point_cloud_translated.points)
            self.all_colors = np.asarray(self.point_cloud_translated.colors) if self.point_cloud_translated.has_colors() else None
            QMessageBox.information(self, "Filtragem Voxel", "Filtragem desativada. Dados originais mantidos.")
            return

        try:
            voxel_size = float(self.lineEdit_voxelSize.text())
            min_points_per_voxel = int(self.lineEdit_pointsPerVoxel.text())
        except ValueError:
            QMessageBox.warning(self, "Erro de Parâmetro", "Tamanho do Voxel e Mínimo de pontos inválidos.")
            return

        current_points = np.asarray(self.point_cloud_translated.points)
        current_colors = np.asarray(self.point_cloud_translated.colors) if self.point_cloud_translated.has_colors() else None

        voxel_coords = np.floor(current_points / voxel_size).astype(int)
        voxel_counts = Counter(map(tuple, voxel_coords))

        keep_mask = np.array([voxel_counts[tuple(vc)] >= min_points_per_voxel for vc in voxel_coords])

        self.all_points = current_points[keep_mask]
        self.all_colors = current_colors[keep_mask] if current_colors is not None else None

        QMessageBox.information(self, "Etapa 2 Concluída", f"Filtragem Concluída! {len(self.all_points)} pontos restantes.")

    def etapa3_executar_segmentacao(self):
        file_path = self.lineEdit_pathFile_Vegetation.text().strip()
        if self.all_points is None or not file_path:
            QMessageBox.warning(self, "Aviso", "Não há pontos na memória ou caminho do arquivo inválido.")
            return

        try:
            dh_max = float(self.lineEdit_distance.text())
            largura_buffer = float(self.lineEdit_buffer.text())
        except ValueError:
            QMessageBox.warning(self, "Erro de Parâmetro", "Os parâmetros de Distância e Buffer devem ser numéricos.")
            return

        total_pontos = len(self.all_points)
        
        # --- ACIONA A BARRA DE PROGRESSO NATIVA NO RODAPÉ DO QGIS 4 ---
        status_bar = self.iface.mainWindow().statusBar()
        progresso_seg = QtWidgets.QProgressBar()
        progresso_seg.setMaximumWidth(250)
        status_bar.addWidget(progresso_seg)
        status_bar.showMessage("SegTree | Passada 1: Agrupando por conectividade 3D...")
        
        ponto_segmento_id = np.full(total_pontos, -1, dtype=int)
        segmentos_pontos_indices = []  

        start_time = time.time()

        def calcular_distancia_2d(p1, p2):
            return np.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

        def calcular_distancia_3d(p1, p2):
            return np.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2 + (p1[2] - p2[2])**2)

        # =====================================================================
        # PASSADA 1: CONECTIVIDADE POR CENTROIDE DINÂMICO INCREMENTAL
        # =====================================================================
        status_bar.showMessage("SegTree | Passada 1: Agrupando por proximidade ao centroide...")
        
        ponto_segmento_id = np.full(total_pontos, -1, dtype=int)
        segmentos_pontos_indices = []  
        
        # Estruturas auxiliares dinâmicas para evitar recalculá-las em loops pesados
        centroides_segmentos = []       # Guardará arrays [X_medio, Y_medio]
        somas_xyz_segmentos = []        # Guardará as somas acumuladas [SomaX, SomaY, SomaZ] para atualizar o centroide
        
        for i in range(total_pontos):
            if i % max(1, total_pontos // 100) == 0:
                percentual = int((i / total_pontos) * 40) # 0% a 40% da barra do QGIS
                progresso_seg.setValue(percentual)
                QtWidgets.QApplication.processEvents()

            if ponto_segmento_id[i] != -1:
                continue

            ponto_atual_xyz = self.all_points[i]
            id_segmento_proximo = -1
            menor_dist_2d = float('inf')

            # Varre as árvores/segmentos já iniciados
            for idx_seg, centroide in enumerate(centroides_segmentos):
                # Calcula a distância planimétrica (2D) até o centroide dinâmico da copa
                dist_2d = np.sqrt((centroide[0] - ponto_atual_xyz[0])**2 + (centroide[1] - ponto_atual_xyz[1])**2)
                
                # [Fato] Critério de Vizinhança por Adjacência Geométrica Urbanística
                if dist_2d <= dh_max and dist_2d < menor_dist_2d:
                    # Verifica também a consistência altimétrica aproximada em relação ao miolo do cluster
                    # Evita que um ponto de fiação elétrica muito alto ou solo muito baixo seja puxado
                    menor_dist_2d = dist_2d
                    id_segmento_proximo = idx_seg

            if id_segmento_proximo != -1:
                # O ponto pertence ao miolo ou borda desta árvore! Assimila o ID
                ponto_segmento_id[i] = id_segmento_proximo
                segmentos_pontos_indices[id_segmento_proximo].append(i)
                
                # Atualização Incremental Rápida do Centroide O(1)
                somas_xyz_segmentos[id_segmento_proximo] += ponto_atual_xyz
                n_pontos = len(segmentos_pontos_indices[id_segmento_proximo])
                centroides_segmentos[id_segmento_proximo] = somas_xyz_segmentos[id_segmento_proximo][:2] / n_pontos
            else:
                # Se o ponto caiu longe de todos os centroides existentes, ele inicia uma nova semente de árvore
                novo_id = len(segmentos_pontos_indices)
                ponto_segmento_id[i] = novo_id
                segmentos_pontos_indices.append([i])
                
                # Inicializa as estruturas acumuladoras para este novo indivíduo
                somas_xyz_segmentos.append(np.copy(ponto_atual_xyz))
                centroides_segmentos.append(np.copy(ponto_atual_xyz[:2]))

        # =====================================================================
        # PASSADA 2: MODELAGEM ORGÂNICA POR UNIÃO DISSOLVIDA DILATADA
        # =====================================================================
        status_bar.showMessage("SegTree | Passada 2: Modelando envelopes orgânicos de copas...")
        
        segmentos_validos_indices = [indices for indices in segmentos_pontos_indices if len(indices) >= 3]
        total_arvores_maduras = len(segmentos_validos_indices)
        
        poligonos_buffers = [None] * total_arvores_maduras

        for idx, indices in enumerate(segmentos_validos_indices):
            if idx % max(1, total_arvores_maduras // 100) == 0:
                percentual = 40 + int((idx / total_arvores_maduras) * 30)
                progresso_seg.setValue(percentual)
                QtWidgets.QApplication.processEvents()

            pontos_segmento = self.all_points[indices]
            
            try:
                # Cria uma geometria multiponto nativa
                lista_pontos_qgis = [QgsPointXY(pt[0], pt[1]) for pt in pontos_segmento]
                geom_multiponto = QgsGeometry.fromMultiPointXY(lista_pontos_qgis)
                
                if geom_multiponto.isGeosValid():
                    # [Fato] O segredo está aqui: o buffer é gerado na escala métrica exata dos pontos,
                    # usando poucos segmentos (3) para criar contornos mais serrilhados e menos inflados.
                    geom_inflada = geom_multiponto.buffer(largura_buffer, 3)
                    
                    # Simplifica o contorno para remover micro-arestas que travam a Passada 3
                    poligonos_buffers[idx] = geom_inflada.simplify(0.05)
                else:
                    poligonos_buffers[idx] = None
            except Exception:
                poligonos_buffers[idx] = None

        # =====================================================================
        # PASSADA 3: FUSÃO TARDIA POR MATRIZ DE AFINIDADE (VERSÃO REPARADA)
        # =====================================================================
        status_bar.showMessage("SegTree | Passada 3: Calculando matriz de sobreposição...")
        
        try:
            # Captura o valor da interface e converte de porcentagem (ex: 25) para decimal (0.25)
            valor_interface = float(self.lineEdit_overlayer.text())
            limiar_overlap = valor_interface / 100.0
        except ValueError:
            limiar_overlap = 0.25
            self.lineEdit_overlayer.setText("25")

        segmentos_finais = []
        arvores_processadas = np.zeros(total_arvores_maduras, dtype=bool)
        
        # =====================================================================
        # 1. FASE DE ESCANEAMENTO ESTÁTICO: MAPEIA O GRAFO DE ADJACÊNCIA
        # =====================================================================
        grafo_fusao = {i: [i] for i in range(total_arvores_maduras)}

        for idx_base in range(total_arvores_maduras):
            if idx_base % max(1, total_arvores_maduras // 100) == 0:
                percentual = 70 + int((idx_base / total_arvores_maduras) * 15) # 70% a 85%
                progresso_seg.setValue(percentual)
                QtWidgets.QApplication.processEvents()

            geom_base = poligonos_buffers[idx_base]
            if geom_base is None or geom_base.isEmpty():
                continue

            area_base = geom_base.area()

            for idx_alvo in range(idx_base + 1, total_arvores_maduras):
                geom_alvo = poligonos_buffers[idx_alvo]
                if geom_alvo is None or geom_alvo.isEmpty():
                    continue

                # Teste topológico rápido de intersecção
                if geom_base.intersects(geom_alvo):
                    intersecção = geom_base.intersection(geom_alvo)
                    if not intersecção.isEmpty():
                        area_intersecção = intersecção.area()
                        area_menor = min(area_base, geom_alvo.area())
                        proporcao_sobreposicao = area_intersecção / area_menor
                        
                        if proporcao_sobreposicao >= limiar_overlap:
                            grafo_fusao[idx_base].append(idx_alvo)
                            grafo_fusao[idx_alvo].append(idx_base)

        # =====================================================================
        # 2. FASE DE CONSOLIDAÇÃO EM LOTE (RESOLUÇÃO DO GRAFO - RECOMPILADA!)
        # =====================================================================
        status_bar.showMessage("SegTree | Passada 3: Consolidando blocos em lote...")
        
        for idx_base in range(total_arvores_maduras):
            if idx_base % max(1, total_arvores_maduras // 100) == 0:
                percentual = 85 + int((idx_base / total_arvores_maduras) * 15) # 85% a 100%
                progresso_seg.setValue(percentual)
                QtWidgets.QApplication.processEvents()

            if arvores_processadas[idx_base] or len(segmentos_validos_indices[idx_base]) == 0:
                continue

            # Busca em Largura (BFS) para colher os nós conectados
            fila_componentes = [idx_base]
            grupo_indices_fundidos = []
            
            while len(fila_componentes) > 0:
                nó_atual = fila_componentes.pop(0)
                if not arvores_processadas[nó_atual]:
                    arvores_processadas[nó_atual] = True
                    grupo_indices_fundidos.extend(segmentos_validos_indices[nó_atual])
                    
                    # Alimenta os vizinhos válidos do grafo
                    for vizinho in grafo_fusao[nó_atual]:
                        if not arvores_processadas[vizinho]:
                            fila_componentes.append(vizinho)

            if len(grupo_indices_fundidos) > 0:
                segmentos_finais.append(grupo_indices_fundidos)

        # Filtra os segmentos consolidados finais exigindo pelo menos 4 pontos
        self.segments = [indices for indices in segmentos_finais if len(indices) >= 4]
        
        # =====================================================================
        # PASSADA 4: PÓS-PROCESSAMENTO RECURSIVO
        # =====================================================================
        # PÓS-PROCESSAMENTO: WATERSHED 3D RESTRITO A MACRO-BLOCO (BLINDADO)
        # =====================================================================
        status_bar.showMessage("SegTree | Pós-processamento: Isolando anomalias...")
        
        from scipy.spatial import KDTree
        
        # Razão de aspecto anatômica para gatilho (Comprimento / Largura)
        limiar_elongacao = 2.0  
        segmentos_lapidados = []

        for idx_seg, indices in enumerate(segmentos_finais):
            if len(indices) < 5:
                continue
                
            pontos_segmento = self.all_points[indices]
            coordenadas_2d = pontos_segmento[:, :2]
            
            # --- TESTE ANATÔMICO DE FORMATO (ELONGAÇÃO VIA CASCA CONVEXA) ---
            is_aglomerado = False
            try:
                hull = ConvexHull(coordenadas_2d)
                vertices = coordenadas_2d[hull.vertices]
                diff = vertices[:, np.newaxis, :] - vertices[np.newaxis, :, :]
                dists_quadradas = np.sum(diff**2, axis=-1)
                raio_maior = np.sqrt(np.max(dists_quadradas))
                area_casca = hull.volume
                raio_menor = area_casca / max(0.001, raio_maior)
                
                if (raio_maior / max(0.001, raio_menor)) >= limiar_elongacao:
                    is_aglomerado = True
            except Exception:
                is_aglomerado = False

            # -----------------------------------------------------------------
            # CASO 1: ÁRVORE NORMAL/ISOLADA ➔ BLINDAGEM ABSOLUTA (NÃO MEXE!)
            # -----------------------------------------------------------------
            if not is_aglomerado:
                # [Fato] Devolve o segmento exatamente como ele veio da Passada 3
                # Isso garante que o que estava dando certo nunca mais seja alterado
                segmentos_lapidados.append(indices)
                continue
            
            # -----------------------------------------------------------------
            # CASO 2: DISTÂNCIA LINEAR SIMPLES EM Z (ISOLAMENTO DO SUB-DOSSEL)
            # -----------------------------------------------------------------
            try:
                indices_np = np.array(indices)
                
                # 1. ORDENAÇÃO CRESCENTE DA NUVEM LOCAL PARA MEDIR A RAMPA DE SUBIDA
                idx_ordenacao_crescente = np.argsort(pontos_segmento[:, 2])
                pts_ordenados = pontos_segmento[idx_ordenacao_crescente]
                global_idx_ordenados = indices_np[idx_ordenacao_crescente]
                
                dl_base = self.distance if hasattr(self, 'distance') else 1.2
                limiar_estouro = 1.5 * dl_base  
                
                ponto_corte = len(pts_ordenados)  
                
                for i in range(1, len(pts_ordenados)):
                    distancia_z_simples = pts_ordenados[i, 2] - pts_ordenados[i - 1, 2]
                    if distancia_z_simples > limiar_estouro:
                        ponto_corte = i
                        break  
                
                global_idx_A = global_idx_ordenados[:ponto_corte]
                global_idx_B = global_idx_ordenados[ponto_corte:]
                
                # [Fato] Se o corte achou sub-dossel, ele vai direto para o resultado final, protegido
                if len(global_idx_A) >= 5:
                    segmentos_lapidados.append(global_idx_A.tolist())
                    
            except Exception as err:
                print(f">>> [SegTree] Erro na Distância Simples em Z (Caso 2): {str(err)}")
                segmentos_lapidados.append(indices)
                continue

            # -----------------------------------------------------------------
            # CASO 3: RESEGMENTAÇÃO DO DOSSEL SUPERIOR (SALVANDO EM VARIÁVEL ISOLADA)
            # -----------------------------------------------------------------
            # [Fato] Esta lista vai guardar temporariamente APENAS as copas fragmentadas
            copas_temporarias = []
            
            try:
                if len(global_idx_B) >= 5:
                    pts_B = pontos_segmento[idx_ordenacao_crescente[ponto_corte:]]
                    
                    x_min, x_max = np.min(pts_B[:, 0]), np.max(pts_B[:, 0])
                    y_min, y_max = np.min(pts_B[:, 1]), np.max(pts_B[:, 1])
                    raio_x = (x_max - x_min) / 2.0
                    raio_y = (y_max - y_min) / 2.0
                    dh_raio = min(raio_x, raio_y) / 2.0
                    
                    if dh_raio < 0.5:
                        dh_raio = 0.5
                    
                    idx_decrescente_B = np.argsort(pts_B[:, 2])[::-1]
                    pts_B_topo = pts_B[idx_decrescente_B]
                    global_idx_B_topo = global_idx_B[idx_decrescente_B]
                    
                    aglomerados_pts = {}  
                    aglomerados_ids = {}  
                    
                    aglomerados_pts[0] = [pts_B_topo[0]]
                    aglomerados_ids[0] = [global_idx_B_topo[0]]
                    proximo_id_aglomerado = 1
                    
                    for i in range(1, len(pts_B_topo)):
                        pt_atual = pts_B_topo[i]
                        p_qgis = QgsPointXY(pt_atual[0], pt_atual[1])
                        geom_ponto = QgsGeometry.fromPointXY(p_qgis)
                        
                        melhor_aglomerado = None
                        menor_distancia = float('inf')
                        
                        for agl_id, lista_pts in aglomerados_pts.items():
                            if len(lista_pts) <= 2:
                                pt_topo_agl = lista_pts[0]
                                dist = np.linalg.norm(pt_atual[:2] - pt_topo_agl[:2])
                            else:
                                try:
                                    pts_matriz = np.array(lista_pts)
                                    hull = ConvexHull(pts_matriz[:, :2])
                                    vertices_casca = [QgsPointXY(pts_matriz[v, 0], pts_matriz[v, 1]) for v in hull.vertices]
                                    geom_casca = QgsGeometry.fromPolygonXY([vertices_casca])
                                    dist = geom_ponto.distance(geom_casca)
                                except Exception:
                                    dist = np.min([np.linalg.norm(pt_atual[:2] - p[:2]) for p in lista_pts])
                            
                            if dist < menor_distancia:
                                menor_distancia = dist
                                melhor_aglomerado = agl_id
                        
                        if melhor_aglomerado is not None and menor_distancia <= dh_raio:
                            aglomerados_pts[melhor_aglomerado].append(pt_atual)
                            aglomerados_ids[melhor_aglomerado].append(global_idx_B_topo[i])
                        else:
                            aglomerados_pts[proximo_id_aglomerado] = [pt_atual]
                            aglomerados_ids[proximo_id_aglomerado] = [global_idx_B_topo[i]]
                            proximo_id_aglomerado += 1
                    
                    # Alimenta a variável de trabalho isolada
                    for agl_id, lista_globais in aglomerados_ids.items():
                        if len(lista_globais) >= 5:
                            copas_temporarias.append(lista_globais)
                            
            except Exception as err:
                print(f">>> [SegTree] Erro no Caso 3: {str(err)}")
                copas_temporarias = [global_idx_B.tolist()] if len(global_idx_B) >= 5 else []

            # -----------------------------------------------------------------
            # CASO 4: FUSÃO POR INTERSECÇÃO DE ÁREAS COM LOG DE DEBUG NO CONSOLE
            # -----------------------------------------------------------------
            try:
                if len(copas_temporarias) > 1:
                    geometrias_casca_c4 = {}
                    geometrias_buffer_c4 = {}
                    areas_buffer_totais = {}
                    
                    dh_tolerancia = self.distance if hasattr(self, 'distance') else 1.2
                    raio_buffer = dh_tolerancia / 2.0  
                    
                    print(f"\n==================================================")
                    print(f"[SegTree C4] RELATÓRIO DE INTERSEÇÃO (Limiar: 30%)")
                    print(f"==================================================")

                    for s_idx, lista_globais in enumerate(copas_temporarias):
                        pts_s = self.all_points[lista_globais]
                        try:
                            hull = ConvexHull(pts_s[:, :2])
                            vertices = [QgsPointXY(pts_s[v, 0], pts_s[v, 1]) for v in hull.vertices]
                            vertices.append(vertices[0])  
                            
                            geom_poligono = QgsGeometry.fromPolygonXY([vertices])
                            geometrias_casca_c4[s_idx] = geom_poligono
                            
                            geom_buffer = geom_poligono.buffer(raio_buffer, 5)
                            geometrias_buffer_c4[s_idx] = geom_buffer
                            areas_buffer_totais[s_idx] = geom_buffer.area()
                        except Exception:
                            idx_max_z = np.argmax(pts_s[:, 2])
                            pt_max = pts_s[idx_max_z]
                            p_qgis = QgsGeometry.fromPointXY(QgsPointXY(pt_max[0], pt_max[1]))
                            geometrias_casca_c4[s_idx] = p_qgis
                            
                            geom_buffer = p_qgis.buffer(raio_buffer, 5)
                            geometrias_buffer_c4[s_idx] = geom_buffer
                            areas_buffer_totais[s_idx] = geom_buffer.area()

                    grafo_unificação = {i: [i] for i in range(len(copas_temporarias))}
                    limiar_proporcao_area = 0.30  
                    
                    for i in range(len(copas_temporarias)):
                        buf_i = geometrias_buffer_c4.get(i)
                        area_buf_i = areas_buffer_totais.get(i, 0.0)
                        
                        if buf_i is None or buf_i.isEmpty() or area_buf_i == 0.0:
                            continue
                            
                        for j in range(len(copas_temporarias)):
                            if i == j:
                                continue
                                
                            buf_j = geometgener_j = geometrias_buffer_c4.get(j)
                            area_buf_j = areas_buffer_totais.get(j, 0.0)
                            
                            if buf_j is None or buf_j.isEmpty() or area_buf_j == 0.0:
                                continue
                            
                            if geometrias_casca_c4[i].distance(geometrias_casca_c4[j]) > dh_tolerancia:
                                # [Log] Avisa se os blocos estão longe demais para sequer tentar o buffer
                                # print(f"Seg {i:02d} -> Seg {j:02d}: Distantes demais (>{dh_tolerancia}m)")
                                continue
                                
                            intersecção_buffers = buf_i.intersection(buf_j)
                            
                            if not intersecção_buffers.isEmpty():
                                area_corte = intersecção_buffers.area()
                                proporcao_i = area_corte / area_buf_i
                                
                                # [Fato] Print legível enviado diretamente para o Console do QGIS
                                status_fusao = "FUSÃO APROVADA" if proporcao_i >= limiar_proporcao_area else "BARRADO"
                                print(f"-> Analisando Seg {i+2:02d} em relação ao Seg {j+2:02d}:")
                                print(f"   Área Buffer Seg {i+2:02d}: {area_buf_i:.3f} m²")
                                print(f"   Área da Interseção: {area_corte:.3f} m²")
                                print(f"   Proporção Obtida  : {proporcao_i * 100:.2f}% (Status: {status_fusao})")
                                print(f"--------------------------------------------------")

                                if proporcao_i >= limiar_proporcao_area:
                                    grafo_unificação[i].append(j)
                                    grafo_unificação[j].append(i)

                    processados_c4 = {i: False for i in range(len(copas_temporarias))}
                    copas_fundidas = []
                    
                    for i in range(len(copas_temporarias)):
                        if processados_c4[i]:
                            continue
                        fila_bfs = [i]
                        grupo_indices_global = []
                        while len(fila_bfs) > 0:
                            atual = fila_bfs.pop(0)
                            if not processados_c4[atual]:
                                processados_c4[atual] = True
                                grupo_indices_global.extend(copas_temporarias[atual])
                                for vizinho in grafo_unificação[atual]:
                                    if not processados_c4[vizinho]:
                                        fila_bfs.append(vizinho)
                        if len(grupo_indices_global) > 0:
                            copas_fundidas.append(grupo_indices_global)
                    
                    segmentos_lapidados.extend(copas_fundidas)
                    print(f"==================================================\n")
                else:
                    segmentos_lapidados.extend(copas_temporarias)

            except Exception as err:
                print(f">>> [SegTree] Erro na Fusão por Intersecção de Buffers (Caso 4): {str(err)}")
                segmentos_lapidados.extend(copas_temporarias)
        
        # =====================================================================
        # CONTROLE DE MÁSCARA E CÁLCULO DE ÓRFÃOS (FINALIZAÇÃO DO SCRIPT)
        # =====================================================================
        pontos_assimilados_mask = np.zeros(total_pontos, dtype=bool)
        for indices in self.segments:
            pontos_assimilados_mask[indices] = True
        pontos_orfaos = int(np.sum(~pontos_assimilados_mask))
        elapsed_time = time.time() - start_time

        # =====================================================================
        # GRAVAÇÃO DOS ARQUIVOS E CARREGAMENTO NO QGIS (VERSÃO ULTRA-ROBUSTA)
        # =====================================================================
        status_bar = self.iface.mainWindow().statusBar() if hasattr(self, 'iface') else None
        if status_bar:
            status_bar.showMessage("SegTree | Exportando segmentos e atualizando camadas...")
        
        # Garante caminhos absolutos e limpos de falhas de sistema
        pasta_raiz = os.path.dirname(os.path.abspath(file_path))
        pasta_resultado = os.path.join(pasta_raiz, "Resultado_Segmentacao")
        
        try:
            if not os.path.exists(pasta_resultado):
                os.makedirs(pasta_resultado)
        except Exception as e:
            QMessageBox.critical(self, "Erro de Permissão", f"O sistema não conseguiu criar a pasta de resultados:\n{pasta_resultado}\n\nMotivo: {str(e)}")
            return

        # Captura segura dos estados dos CheckBoxes originais da sua interface
        salvar_las = self.checkBox_las.isChecked() if hasattr(self, 'checkBox_las') else False
        salvar_laz = self.checkBox_laz.isChecked() if hasattr(self, 'checkBox_laz') else False
        salvar_xyz = self.checkBox_xyz.isChecked() if hasattr(self, 'checkBox_xyz') else False
        abrir_no_qgis = self.checkBox_openQGis.isChecked() if hasattr(self, 'checkBox_openQGis') else False

        total_segmentos = len(segmentos_lapidados)
        arquivos_para_abrir = []

        # Loop de exportação baseado na lista unificada de ponteiros (OK + Caso 2)
        for idx, lista_indices_segmento in enumerate(segmentos_lapidados):
            if hasattr(self, '_is_cancelled') and self._is_cancelled:
                break

            # Extrai a geometria bruta local do segmento para aplicar a ordenação por altura
            pontos_segmento = self.all_points[lista_indices_segmento]
            
            # 1. ORDENAÇÃO DECRESCENTE POR Z (DO TOPO PARA O CHÃO)
            idx_ordenacao_decrescente = np.argsort(pontos_segmento[:, 2])[::-1]
            pontos_ordenados = pontos_segmento[idx_ordenacao_decrescente]
            
            # 2. DEVOLVE O GEORREFERENCIAMENTO ABSOLUTO APENAS NA MATRIZ DE EXPORTAÇÃO
            pontos_originais = np.copy(pontos_ordenados)
            pontos_originais[:, 0] += self.minimoX
            pontos_originais[:, 1] += self.minimoY
            
            nome_base = os.path.join(pasta_resultado, f"segmento_{idx+1:02d}")

            # --- EXPORTAÇÃO SELECIONADA: XYZ (COM ORDENAÇÃO CORRIGIDA) ---
            if salvar_xyz:
                nome_xyz = f"{nome_base}.xyz"
                with open(nome_xyz, 'w', encoding='utf-8') as f_xyz:
                    for pt in pontos_originais:
                        f_xyz.write(f"{pt[0]:.3f} {pt[1]:.3f} {pt[2]:.3f}\n")
                if abrir_no_qgis:
                    arquivos_para_abrir.append(nome_xyz)

            # --- EXPORTAÇÃO SELECIONADA: LAS / LAZ (COM ORDENAÇÃO CORRIGIDA) ---
            if salvar_las or salvar_laz:
                try:
                    import laspy
                    header = laspy.LasHeader(point_format=3, version="1.2")
                    header.offsets = [self.minimoX, self.minimoY, 0]
                    header.scales = [0.001, 0.001, 0.001]
                    
                    nome_las = f"{nome_base}.las" if salvar_las else f"{nome_base}.laz"
                    with laspy.open(nome_las, mode="w", header=header) as writer:
                        point_record = laspy.ScaleAwarePointRecord.zeros(len(pontos_originais), header=header)
                        point_record.x = pontos_originais[:, 0]
                        point_record.y = pontos_originais[:, 1]
                        point_record.z = pontos_originais[:, 2]
                        writer.write_points(point_record)
                    if abrir_no_qgis and not salvar_xyz:
                        arquivos_para_abrir.append(nome_las)
                except ImportError:
                    print(">>> [SegTree] Biblioteca laspy não instalada para exportação.")

            # Atualiza dinamicamente o progresso do Worker na barra do QGIS
            if hasattr(self, 'progress') and hasattr(self, 'status'):
                progresso_atual = 50 + int((idx + 1) / total_segmentos * 50)
                self.progress.emit(progresso_atual)
                self.status.emit(f"Exportando e georreferenciando: {idx + 1}/{total_segmentos}")

        # =====================================================================
        # CARREGAMENTO INTELIGENTE E SEGURO NO QGIS 4 (FALLBACK DE FORMATOS)
        # =====================================================================
        if abrir_no_qgis:
            from qgis.core import QgsProject, QgsVectorLayer, QgsPointCloudLayer
            status_bar.showMessage("SegTree | Renderizando copas na tela do mapa...")

            # Varre os segmentos consolidados para carregar o melhor formato disponível
            for idx in range(total_segmentos):
                nome_base = os.path.join(pasta_resultado, f"segmento_{idx+1:02d}")
                
                caminho_las = f"{nome_base}.las"
                caminho_las_fallback = f"{nome_base}_fallback.las"
                caminho_laz = f"{nome_base}.laz"
                caminho_xyz = f"{nome_base}.xyz"
                
                camada_carregada = False
                nome_camada = f"Copa_{idx+1:02d}"

                # --- PRIORIDADE 1: Tenta carregar o arquivo compactado .LAZ ---
                if salvar_laz and os.path.exists(caminho_laz) and not camada_carregada:
                    camada = QgsPointCloudLayer(caminho_laz, f"{nome_camada} (LAZ)", "pointcloud")
                    if camada.isValid():
                        QgsProject.instance().addMapLayer(camada)
                        camada_carregada = True

                # --- PRIORIDADE 2: Tenta carregar o arquivo padrão .LAS ---
                if salvar_las and os.path.exists(caminho_las) and not camada_carregada:
                    camada = QgsPointCloudLayer(caminho_las, f"{nome_camada} (LAS)", "pointcloud")
                    if camada.isValid():
                        QgsProject.instance().addMapLayer(camada)
                        camada_carregada = True

                # --- PRIORIDADE 3: Tenta carregar o arquivo de Fallback .LAS (Se o LAZ falhou) ---
                if salvar_laz and os.path.exists(caminho_las_fallback) and not camada_carregada:
                    camada = QgsPointCloudLayer(caminho_las_fallback, f"{nome_camada} (LAS-FB)", "pointcloud")
                    if camada.isValid():
                        QgsProject.instance().addMapLayer(camada)
                        camada_carregada = True

                # --- PRIORIDADE 4: Fallback Final - Se nada acima funcionou ou existiu, vai de .XYZ ---
                if os.path.exists(caminho_xyz) and not camada_carregada:
                    # Formata a URI para o leitor de texto delimitado do QGIS
                    uri = f"file:///{caminho_xyz.replace('\\', '/')}?delimiter= &xField=field_1&yField=field_2&zField=field_3"
                    camada = QgsVectorLayer(uri, f"{nome_camada} (XYZ)", "delimitedtext")
                    if camada.isValid():
                        QgsProject.instance().addMapLayer(camada)
                        camada_carregada = True

        # =====================================================================
        # FINALIZAÇÃO DO PROCESSO
        # =====================================================================
        progresso_seg.setValue(100)
        status_bar.removeWidget(progresso_seg)
        status_bar.showMessage("SegTree | Processo concluído com sucesso!", 5000)

        QMessageBox.information(
            self, "Processo Concluído", 
            f"Segmentação Avançada Concluída com Sucesso!\n\n"
            f"Total de indivíduos individuais consolidados: {total_segmentos}\n"
            f"Pontos isolados não assimilados (órfãos): {pontos_orfaos} ({ (pontos_orfaos/total_pontos)*100:.1f}% da nuvem)\n"
            f"Ficheiros exportados e carregados com segurança na pasta:\n{pasta_resultado}"
        )

# =====================================================================
# CLASSE DE CICLO DE VIDA DO PLUGIN (Gerenciada pelo QGIS)
# =====================================================================
class SegTree:
    def __init__(self, iface):
        """Inicializa as variáveis principais de controle do QGIS."""
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dlg = None

    def initGui(self):
        """Cria o botão na barra de ferramentas principal e nos menus do QGIS 4."""
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        
        # Cria a ação principal
        self.action = QAction(icon, 'SegTree - Segmentador de Árvores', self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        
        # --- FORÇA BRUTA: Adiciona na barra de ferramentas PRINCIPAL (junto com o Reloader) ---
        self.iface.addToolBarIcon(self.action)
        
        # Adiciona também no menu de Complementos geral para não ter erro
        self.iface.addPluginToMenu('&SegTree', self.action)
        
        # Print secreto que vai aparecer no Console de Python do QGIS para provar que rodou
        print(">>> [SegTree] Plugin inicializado e botões criados com sucesso!")

    def unload(self):
        """Remove o botão de todos os lugares ao desativar."""
        if self.action:
            # Remove da barra principal
            self.iface.removeToolBarIcon(self.action)
            # Remove do menu geral
            self.iface.removePluginMenu('&SegTree', self.action)
            print(">>> [SegTree] Plugin descarregado com sucesso!")

    def run(self):
        """Método principal acionado ao clicar no ícone do plugin."""
        # Instancia a janela passando o iface e definindo a janela do QGIS como parent legítimo
        if self.dlg is None:
            self.dlg = SegTreeDialog(iface=self.iface, parent=self.iface.mainWindow())

        # Atualiza o estado dos botões e travas lógicas antes de exibir
        self.dlg.atualizar_estado_widgets_aba1()
        self.dlg.atualizar_estado_widgets_aba2()

        # Garante que a janela venha para a frente
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()
        self.dlg.exec()
        
# Garante compatibilidade com o classFactory do __init__.py do Plugin Builder
PluginMain = SegTree