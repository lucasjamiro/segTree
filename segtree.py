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
        self.lineEdit_buffer.setText("2.0")
        
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
        # PASSADA 1: CONECTIVIDADE DIRETA 3D (DH_MAX)
        # =====================================================================
        for i in range(total_pontos):
            if i % max(1, total_pontos // 100) == 0:
                percentual = int((i / total_pontos) * 40) # 0% a 40% da barra do QGIS
                progresso_seg.setValue(percentual)
                QtWidgets.QApplication.processEvents()

            if ponto_segmento_id[i] != -1:
                continue

            ponto_atual_xyz = self.all_points[i]
            id_segmento_proximo = -1
            menor_dist_3d = float('inf')

            for idx_arvore, indices_arvore in enumerate(segmentos_pontos_indices):
                ultimo_pnto_arvore = self.all_points[indices_arvore[-1]]
                dist_3d = calcular_distancia_3d(ultimo_pnto_arvore, ponto_atual_xyz)
                
                if dist_3d <= dh_max and dist_3d < menor_dist_3d:
                    menor_dist_3d = dist_3d
                    id_segmento_proximo = idx_arvore

            if id_segmento_proximo != -1:
                ponto_segmento_id[i] = id_segmento_proximo
                segmentos_pontos_indices[id_segmento_proximo].append(i)
            else:
                novo_id = len(segmentos_pontos_indices)
                ponto_segmento_id[i] = novo_id
                segmentos_pontos_indices.append([i])

        # =====================================================================
        # PASSADA 2: FILTRAGEM DE CONSISTÊNCIA E MODELAGEM DE CASCA VETORIAL
        # =====================================================================
        status_bar.showMessage("SegTree | Passada 2: Modelando envelopes das copas no QGIS...")
        segmentos_validos_indices = [indices for indices in segmentos_pontos_indices if len(indices) >= 4]
        total_arvores_maduras = len(segmentos_validos_indices)
        
        poligonos_buffers = [None] * total_arvores_maduras

        for idx, indices in enumerate(segmentos_validos_indices):
            if idx % max(1, total_arvores_maduras // 100) == 0:
                percentual = 40 + int((idx / total_arvores_maduras) * 30) # 40% a 70% da barra do QGIS
                progresso_seg.setValue(percentual)
                QtWidgets.QApplication.processEvents()

            pontos_segmento = self.all_points[indices]
            try:
                hull = ConvexHull(pontos_segmento[:, :2])
                polygon_points = pontos_segmento[hull.vertices, :2]
                qgis_points = [QgsPointXY(pt[0], pt[1]) for pt in polygon_points]
                poly_geom = QgsGeometry.fromPolygonXY([qgis_points])
                poligonos_buffers[idx] = poly_geom.buffer(largura_buffer, 8, 3, 3, 2.0)
            except Exception:
                poligonos_buffers[idx] = None

        # =====================================================================
        # PASSADA 3: FUSÃO DE COMPONENTES ADJACENTES (SUA DISSERTAÇÃO)
        # =====================================================================
        status_bar.showMessage("SegTree | Passada 3: Executando fusão de contornos contíguos...")
        segmentos_finais = []
        arvores_processadas = np.zeros(total_arvores_maduras, dtype=bool)

        for idx_base in range(total_arvores_maduras):
            if idx_base % max(1, total_arvores_maduras // 100) == 0:
                percentual = 70 + int((idx_base / total_arvores_maduras) * 30) # 70% a 100% da barra do QGIS
                progresso_seg.setValue(percentual)
                QtWidgets.QApplication.processEvents()

            if arvores_processadas[idx_base]:
                continue

            grupo_indices_fundidos = list(segmentos_validos_indices[idx_base])
            arvores_processadas[idx_base] = True
            geom_base = poligonos_buffers[idx_base]

            if geom_base is not None:
                for idx_alvo in range(idx_base + 1, total_arvores_maduras):
                    if arvores_processadas[idx_alvo]:
                        continue
                    
                    geom_alvo = poligonos_buffers[idx_alvo]
                    if geom_alvo is not None:
                        if geom_base.intersects(geom_alvo):
                            grupo_indices_fundidos.extend(segmentos_validos_indices[idx_alvo])
                            arvores_processadas[idx_alvo] = True
                            geom_base = geom_base.combine(geom_alvo)

            segmentos_finais.append(grupo_indices_fundidos)

        self.segments = [indices for indices in segmentos_finais if len(indices) >= 4]
        
        # Mapeia os pontos assimilados para extrair a contagem exata de pontos órfãos
        pontos_assimilados_mask = np.zeros(total_pontos, dtype=bool)
        for indices in self.segments:
            pontos_assimilados_mask[indices] = True
        
        pontos_orfaos = int(np.sum(~pontos_assimilados_mask))
        elapsed_time = time.time() - start_time

        # =====================================================================
        # GRAVAÇÃO DOS ARQUIVOS E CARREGAMENTO NO QGIS (VERSÃO ULTRA-ROBUSTA)
        # =====================================================================
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

        # Captura segura dos estados dos CheckBoxes
        salvar_las = self.checkBox_las.isChecked() if hasattr(self, 'checkBox_las') else False
        salvar_laz = self.checkBox_laz.isChecked() if hasattr(self, 'checkBox_laz') else False
        salvar_xyz = self.checkBox_xyz.isChecked() if hasattr(self, 'checkBox_xyz') else False
        abrir_no_qgis = self.checkBox_openQGis.isChecked() if hasattr(self, 'checkBox_openQGis') else False

        total_segmentos = len(self.segments)
        arquivos_para_abrir = []

        for idx, indices in enumerate(self.segments):
            pontos_segmento = self.all_points[indices]
            pontos_originais = np.copy(pontos_segmento)
            
            # Devolve o georreferenciamento absoluto
            pontos_originais[:, 0] += self.minimoX
            pontos_originais[:, 1] += self.minimoY
            
            nome_base = os.path.join(pasta_resultado, f"segmento_{idx+1:02d}")

            # --- Formato 1: .XYZ (Texto Plano) ---
            if salvar_xyz:
                caminho_xyz = f"{nome_base}.xyz"
                try:
                    np.savetxt(caminho_xyz, pontos_originais, fmt="%.3f", delimiter=" ")
                    if abrir_no_qgis:
                        # Arquivos XYZ entram no QGIS 4 como vetor delimitado por texto (delimitedtext)
                        uri = f"file:///{caminho_xyz.replace('\\', '/')}?delimiter= &xField=field_1&yField=field_2&zField=field_3"
                        arquivos_para_abrir.append((uri, f"Copa_{idx+1:02d} (XYZ)", "delimitedtext"))
                except Exception as e:
                    if idx == 0:
                        QMessageBox.warning(self, "Falha de Escrita", f"Erro ao gravar arquivo .xyz:\n{str(e)}")

            # --- Formatos 2 e 3: .LAS / .LAZ (Binários) ---
            if salvar_las or salvar_laz:
                try:
                    import laspy
                    header = laspy.LasHeader(point_format=0, version="1.2")
                    header.offsets = [self.minimoX, self.minimoY, 0]
                    header.scales = [0.001, 0.001, 0.001]

                    if salvar_las:
                        caminho_las = f"{nome_base}.las"
                        las_file = laspy.LasData(header)
                        las_file.x = pontos_originais[:, 0]
                        las_file.y = pontos_originais[:, 1]
                        las_file.z = pontos_originais[:, 2]
                        with laspy.open(caminho_las, mode="w", header=header) as writer:
                            writer.write_points(las_file.points)
                        if abrir_no_qgis:
                            arquivos_para_abrir.append((caminho_las, f"Copa_{idx+1:02d} (LAS)", "pointcloud"))

                    # --- Formato 3: .LAZ (CORRIGIDO E FORÇADO) ---
                    if salvar_laz:
                        caminho_laz = f"{nome_base}.laz"
                        las_file = laspy.LasData(header)
                        las_file.x = pontos_originais[:, 0]
                        las_file.y = pontos_originais[:, 1]
                        las_file.z = pontos_originais[:, 2]
                        
                        try:
                            # Importa o enumerador de backends do laspy moderno
                            from laspy.compression import LazBackend
                            
                            # [Inferido] Tenta abrir especificando explicitamente o lazrs que instalamos
                            with laspy.open(caminho_laz, mode="w", header=header, laz_backend=LazBackend.Lazrs) as writer:
                                writer.write_points(las_file.points)
                            
                            if abrir_no_qgis:
                                arquivos_para_abrir.append((caminho_laz, f"Copa_{idx+1:02d} (LAZ)", "pointcloud"))
                        
                        except Exception as e:
                            # FALLBACK SEGURO: Se o backend falhar por amarrações do QGIS, converte para .las automaticamente
                            if idx == 0:
                                QMessageBox.warning(
                                    self, "Aviso de Compressão",
                                    f"O QGIS não conseguiu inicializar o compressor binário (.laz).\n\n"
                                    f"Motivo: {str(e)}\n\n"
                                    f"Para não perder os dados, o SegTree salvará este formato como .las (descompactado) automaticamente."
                                )
                            
                            # Altera a rota para gerar o arquivo .las correspondente
                            caminho_fallback_las = f"{nome_base}_fallback.las"
                            with laspy.open(caminho_fallback_las, mode="w", header=header) as writer:
                                writer.write_points(las_file.points)
                            
                            if abrir_no_qgis:
                                arquivos_para_abrir.append((caminho_fallback_las, f"Copa_{idx+1:02d} (LAS)", "pointcloud"))
                                
                except Exception as e:
                    if idx == 0:
                        QMessageBox.warning(self, "Falha de Escrita Binária", f"Erro ao processar estrutura LAS/LAZ:\n{str(e)}")

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