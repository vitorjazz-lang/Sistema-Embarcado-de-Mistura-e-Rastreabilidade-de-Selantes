import os
import cv2
import json
import re
import time
import threading
from datetime import datetime, timedelta
from gpiozero import PWMLED, OutputDevice

# ============================================================================
# CONFIGURAÇÃO DE HARDWARE (fixa - características físicas da máquina)
# ============================================================================
PUL_PIN = 18       # Pino Físico 12 (PWM0) - Pulso do motor de passo
DIR_PIN = 27       # Pino Físico 13       - Direção do motor de passo
VALVE_EXT = 23     # Pino Físico 16       - Avanço do pistão (eletroválvula)
VALVE_RET = 24     # Pino Físico 18       - Recuo do pistão (eletroválvula)

MICROSTEPS = 1600  # Passos/volta configurados no driver DM860D
TEMPO_RAMPA = 5.0  # Duração da rampa de aceleração/desaceleração (segundos)

# --- CICLO DO PISTÃO: calibrado em teste_cilindro_10_20cm.py ---
TEMPO_HOMING = 0               # Extensão inicial de referência ao fim de curso (20 cm). 0 = pistão já referenciado
TEMPO_AVANCO_10_20 = 0.23      # Tempo de avanço: 10 cm -> 20 cm
TEMPO_RECUO_20_10 = 0.8        # Tempo de recuo: 20 cm -> 10 cm
PAUSA_ENTRE_MOVIMENTOS = 0.23  # Pausa com centro fechado entre movimentos


# ============================================================================
# CONTROLE DA MÁQUINA (motor de passo + pistão pneumático)
# ============================================================================
class MaquinaSelante:
    def __init__(self):
        self.motor_pulso = PWMLED(PUL_PIN, initial_value=0, frequency=100)
        self.motor_direcao = OutputDevice(DIR_PIN, initial_value=False)  # True = LOW
        self.valvula_ext = OutputDevice(VALVE_EXT, initial_value=False)
        self.valvula_ret = OutputDevice(VALVE_RET, initial_value=False)
        self._inicializar_hardware()

    def _inicializar_hardware(self):
        """Estado inicial seguro: motor parado e pistão recuado"""
        self.motor_pulso.value = 0
        self.motor_direcao.on()
        self._desativar_todas_valvulas()
        self.valvula_ret.on()

    def _desativar_todas_valvulas(self):
        self.valvula_ext.off()
        self.valvula_ret.off()

    def parada_emergencia(self):
        """Parada imediata dos atuadores. Não executa recuo automático."""
        try:
            self.motor_pulso.value = 0
            self._desativar_todas_valvulas()
        except Exception as e:
            print(f"⚠️ Erro ao executar parada de emergência: {e}")

    def executar_ciclo(
        self,
        rpm,
        tempo_total_s,
        total_ciclos_pistao,
        stop_event=None,
        progress_callback=None
    ):
        """
        Executa motor e pistão em paralelo.
        stop_event permite parada imediata por emergência.
        progress_callback(restante_s, stroke_atual, total_strokes) atualiza a IHM.
        """
        if stop_event is None:
            stop_event = threading.Event()

        freq_alvo = (rpm / 100) * MICROSTEPS
        estado = {
            "executando": True,
            "stroke_atual": 0,
            "restante_s": tempo_total_s
        }

        def controlar_motor():
            inicio = time.perf_counter()
            self.motor_pulso.value = 0.5

            while estado["executando"] and not stop_event.is_set():
                agora = time.perf_counter()
                decorrido = agora - inicio

                if decorrido >= tempo_total_s:
                    estado["restante_s"] = 0.0
                    estado["executando"] = False
                    break

                estado["restante_s"] = max(0.0, tempo_total_s - decorrido)

                if decorrido < TEMPO_RAMPA:
                    freq = (decorrido / TEMPO_RAMPA) * freq_alvo
                elif decorrido > (tempo_total_s - TEMPO_RAMPA):
                    restante = tempo_total_s - decorrido
                    freq = (restante / TEMPO_RAMPA) * freq_alvo
                else:
                    freq = freq_alvo

                if freq < 10.0:
                    freq = 10.0

                self.motor_pulso.frequency = freq
                time.sleep(0.05)

            self.motor_pulso.value = 0

        def controlar_pistao():
            if total_ciclos_pistao <= 0:
                return

            # Referência inicial: leva o pistão ao fim de curso (20 cm)
            if TEMPO_HOMING > 0:
                self._desativar_todas_valvulas()
                self.valvula_ext.on()
                if stop_event.wait(TEMPO_HOMING):
                    self._desativar_todas_valvulas()
                    return
                self._desativar_todas_valvulas()
                if stop_event.wait(PAUSA_ENTRE_MOVIMENTOS):
                    return

            for idx in range(1, total_ciclos_pistao + 1):
                if not estado["executando"] or stop_event.is_set():
                    break

                # 20 cm -> 10 cm
                self._desativar_todas_valvulas()
                self.valvula_ret.on()

                if stop_event.wait(TEMPO_RECUO_20_10):
                    break

                self._desativar_todas_valvulas()

                if stop_event.wait(PAUSA_ENTRE_MOVIMENTOS):
                    break

                if not estado["executando"] or stop_event.is_set():
                    break

                # 10 cm -> 20 cm
                self.valvula_ext.on()

                if stop_event.wait(TEMPO_AVANCO_10_20):
                    break

                self._desativar_todas_valvulas()

                estado["stroke_atual"] = idx

                if stop_event.wait(PAUSA_ENTRE_MOVIMENTOS):
                    break

            self._desativar_todas_valvulas()

        thread_motor = threading.Thread(target=controlar_motor, daemon=True)
        thread_pistao = threading.Thread(target=controlar_pistao, daemon=True)

        print(
            f"⚙️ Iniciando ciclo | RPM: {rpm} | Tempo: {tempo_total_s:.0f}s | "
            f"Ciclos: {total_ciclos_pistao}"
        )

        thread_motor.start()
        thread_pistao.start()

        ultimo_segundo_exibido = -1

        while thread_motor.is_alive() or thread_pistao.is_alive():
            if stop_event.is_set():
                estado["executando"] = False
                self.parada_emergencia()
                break

            if progress_callback is not None:
                seg_restante = int(round(estado["restante_s"]))
                if seg_restante != ultimo_segundo_exibido:
                    ultimo_segundo_exibido = seg_restante
                    progress_callback(
                        estado["restante_s"],
                        estado["stroke_atual"],
                        total_ciclos_pistao
                    )

            time.sleep(0.05)

        thread_motor.join(timeout=1.0)
        thread_pistao.join(timeout=1.0)

        if stop_event.is_set():
            self.parada_emergencia()
            print("🛑 CICLO INTERROMPIDO POR EMERGÊNCIA.")
            return False

        if progress_callback is not None:
            progress_callback(0.0, estado["stroke_atual"], total_ciclos_pistao)

        print("✅ Ciclo concluído com sucesso!\n")
        return True

    def finalizar(self):
        """Encerra e desativa todos os atuadores com segurança."""
        print("\nEncerrando e desativando atuadores...")
        self.motor_pulso.value = 0

        self._desativar_todas_valvulas()
        self.valvula_ret.on()
        time.sleep(0.2)
        self._desativar_todas_valvulas()

        self.motor_pulso.close()
        self.motor_direcao.close()
        self.valvula_ext.close()
        self.valvula_ret.close()


# ============================================================================
# RECONHECIMENTO DE QR CODE (sem janela de vídeo - modo headless)
# ============================================================================
class SelaQRRecognizer:
    def __init__(self):
        print("🔄 Inicializando leitor de QR Code USB...")
        self.detector = cv2.QRCodeDetector()

        self.database = self.load_database()
        self.codes_by_key = {
            self.normalize_code(item["code"]): item
            for item in self.database["codes"]
        }

        print(
            f"✅ Pronto! {len(self.codes_by_key)} selas carregadas: "
            f"{', '.join(item['code'] for item in self.database['codes'])}"
        )

    def load_database(self):
        try:
            with open('database.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                if "codes" not in data:
                    data["codes"] = []
                return data
        except FileNotFoundError:
            print("⚠️ database.json não encontrado, criando vazio...")
            return {"codes": []}
        except json.JSONDecodeError:
            print("❌ Erro ao ler database.json")
            return {"codes": []}

    def normalize_code(self, text):
        return re.sub(r'[\s\-_]+', '', text.strip().lower())

    def search_in_database(self, text):
        key = self.normalize_code(text)
        return self.codes_by_key.get(key)

    def decode_qrcode(self, frame):
        """Decodifica 1 QR Code por frame (mais leve para a CPU da Raspberry Pi 4B)."""
        try:
            text, points, _ = self.detector.detectAndDecode(frame)
        except cv2.error:
            return None

        if points is None or not text:
            return None

        return text

    def esperar_leitura(self, stop_event):
        """
        Lê QR Code através da USB Cam sem exibir vídeo.
        Retorna o item do database.json ou None.
        """
        camera_index = 0

        print(f"📷 Abrindo câmera USB (/dev/video{camera_index})...")

        cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)

        if not cap.isOpened():
            raise RuntimeError(
                f"Não foi possível abrir a câmera USB /dev/video{camera_index}."
            )

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        time.sleep(1)

        try:
            while not stop_event.is_set():
                ret, frame = cap.read()

                if not ret:
                    time.sleep(0.05)
                    continue

                decoded_text = self.decode_qrcode(frame)

                if decoded_text:
                    item = self.search_in_database(decoded_text)

                    if item:
                        print(f"🎯 QR Code reconhecido: {item['code']}")
                        time.sleep(0.3)
                        return item

        finally:
            cap.release()

        return None


# ============================================================================
# RASTREABILIDADE: SENSOR AMBIENTAL, LOG JSONL E IMPRESSÃO TÉRMICA (ZPL)
# ============================================================================
class RastreabilidadeSelante:
    def __init__(self, arquivo_log="logs_batimentos.jsonl", porta_impressora="/dev/usb/lp0"):
        self.arquivo_log = arquivo_log
        self.porta_impressora = porta_impressora

    def ler_ambiente(self):
        """
        Lê temperatura (°C) e umidade (%) do sensor na câmara.
        Substitua os valores simulados pela leitura real do seu sensor (ex: DHT22 ou SHT3x).
        """
        try:
            # Exemplo com DHT22:
            # temperatura = round(dht_device.temperature, 1)
            # umidade = round(dht_device.humidity, 1)
            temperatura = 24.5  # Valor simulado até conectar o sensor físico
            umidade = 52.0      # Valor simulado até conectar o sensor físico
            return temperatura, umidade
        except Exception as e:
            print(f"⚠️ Falha ao ler sensor ambiental: {e}")
            return None, None

    def registrar_log(self, item_sela):
        """Gera o registro completo com horário, clima, validade e dados do database.json."""
        agora = datetime.now()
        temperatura, umidade = self.ler_ambiente()

        minutos_validade = item_sela.get("validade_uso_min")
        if isinstance(minutos_validade, (int, float)) and minutos_validade > 0:
            vencimento = (agora + timedelta(minutes=minutos_validade)).strftime("%d/%m/%Y %H:%M")
        else:
            vencimento = (
                item_sela.get("tempo_aplicacao_worklife")
                or item_sela.get("tempo_min_aplicacao")
                or "N/A"
            )

        registro = {
            "id_lote_interno": agora.strftime("%Y%m%d%H%M%S"),
            "data_hora_batimento": agora.strftime("%d/%m/%Y %H:%M:%S"),
            "horario_limite_uso": vencimento,
            "temperatura_ambiente_c": temperatura,
            "umidade_ambiente_pct": umidade,
            "dados_selante": item_sela
        }

        try:
            with open(self.arquivo_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(registro, ensure_ascii=False) + "\n")
            print(f"📝 Log gravado com sucesso: Lote {registro['id_lote_interno']}")
        except Exception as e:
            print(f"❌ Erro ao salvar log: {e}")

        return registro

    def imprimir_etiqueta_zpl(self, registro):
        """Gera o layout ZPL com os dados do log e envia para a impressora térmica USB."""
        sela = registro["dados_selante"]
        temp_str = (
            f"{registro['temperatura_ambiente_c']} C"
            if registro["temperatura_ambiente_c"] is not None
            else "N/A"
        )
        umid_str = (
            f"{registro['umidade_ambiente_pct']} %"
            if registro["umidade_ambiente_pct"] is not None
            else "N/A"
        )

        zpl = f"""
^XA
^CI28
^CF0,28
^FO20,20^FDSELANTE: {sela.get('name', 'N/A')} ({sela.get('code', '')})^FS
^CF0,20
^FO20,55^FDTipo: {sela.get('type', 'N/A')} | RPM: {sela.get('rpm')} | Strokes: {sela.get('ciclo_strokes')}^FS
^FO20,82^FDBatido em: {registro['data_hora_batimento']}^FS
^FO20,108^FDUsar ate (Worklife): {registro['horario_limite_uso']}^FS
^FO20,134^FDCura: {sela.get('tempo_cura', 'N/A')} | Tack Free: {sela.get('track_free_time', 'N/A')}^FS
^FO20,160^FDAmbiente: Temp {temp_str} | Umid {umid_str}^FS
^BY2,2,45
^FO20,190^BCN,45,Y,N,N
^FD{registro['id_lote_interno']}^FS
^XZ
""".strip()

        try:
            if os.path.exists(self.porta_impressora):
                with open(self.porta_impressora, "wb") as printer:
                    printer.write(zpl.encode("utf-8"))
                print("🖨️ Etiqueta enviada para a impressora térmica!")
            else:
                print(
                    f"⚠️ Impressora não encontrada em {self.porta_impressora}. "
                    f"ZPL gerado:\n{zpl}"
                )
        except Exception as e:
            print(f"❌ Erro na impressão térmica: {e}")


# ============================================================================
# PROGRAMA PRINCIPAL (IHM 800x480)
# ============================================================================
def main():
    import tkinter as tk
    from tkinter import messagebox

    print("=" * 70)
    print("🚀 MÁQUINA SELANTE - Interface 800x480")
    print("=" * 70)

    maquina = None
    root = None

    try:
        maquina = MaquinaSelante()
        recognizer = SelaQRRecognizer()
        rastreio = RastreabilidadeSelante()

        emergencia = threading.Event()
        encerrando = threading.Event()

        root = tk.Tk()
        root.title("Máquina Selante")
        root.geometry("800x480")
        root.resizable(False, False)
        root.configure(bg="#101820")

        status_var = tk.StringVar(value="AGUARDANDO QR CODE")
        codigo_var = tk.StringVar(value="Nenhuma sela reconhecida")
        progresso_var = tk.StringVar(value="Tempo restante: --:--  |  Strokes: 0/0")

        # Cabeçalho
        header = tk.Frame(root, bg="#101820")
        header.pack(fill="x", padx=16, pady=(10, 2))

        tk.Label(
            header,
            text="MÁQUINA SELANTE",
            font=("DejaVu Sans", 20, "bold"),
            fg="white",
            bg="#101820"
        ).pack(side="left")

        status_label = tk.Label(
            header,
            textvariable=status_var,
            font=("DejaVu Sans", 13, "bold"),
            fg="#55ff88",
            bg="#101820"
        )
        status_label.pack(side="right")

        # Código reconhecido + Barra de progresso/cronômetro
        info_bar = tk.Frame(root, bg="#101820")
        info_bar.pack(fill="x", padx=16, pady=(2, 6))

        tk.Label(
            info_bar,
            textvariable=codigo_var,
            font=("DejaVu Sans", 16, "bold"),
            fg="white",
            bg="#101820"
        ).pack(side="left")

        tk.Label(
            info_bar,
            textvariable=progresso_var,
            font=("DejaVu Sans", 14, "bold"),
            fg="#ffdd55",
            bg="#101820"
        ).pack(side="right")

        # Área de dados
        data_frame = tk.Frame(root, bg="#18242d", bd=1, relief="solid")
        data_frame.pack(fill="both", expand=True, padx=16, pady=4)

        data_text = tk.Text(
            data_frame,
            font=("DejaVu Sans", 12),
            fg="white",
            bg="#18242d",
            insertbackground="white",
            relief="flat",
            bd=0,
            wrap="word"
        )
        data_text.pack(fill="both", expand=True, padx=14, pady=8)
        data_text.configure(state="disabled")

        def mostrar_dados(item, registro_log=None):
            data_text.configure(state="normal")
            data_text.delete("1.0", tk.END)

            for chave, valor in item.items():
                if isinstance(valor, (dict, list)):
                    valor_formatado = json.dumps(
                        valor, ensure_ascii=False, indent=2
                    )
                else:
                    valor_formatado = "N/A" if valor is None else str(valor)

                data_text.insert(
                    tk.END,
                    f"{chave.upper():<25}: {valor_formatado}\n"
                )

            if registro_log is not None:
                data_text.insert(tk.END, "-" * 58 + "\n")
                data_text.insert(
                    tk.END,
                    f"{'LOTE GERADO':<25}: {registro_log['id_lote_interno']}\n"
                )
                data_text.insert(
                    tk.END,
                    f"{'DATA/HORA BATIMENTO':<25}: {registro_log['data_hora_batimento']}\n"
                )
                data_text.insert(
                    tk.END,
                    f"{'AMBIENTE (TEMP / UMID)':<25}: "
                    f"{registro_log['temperatura_ambiente_c']} °C / "
                    f"{registro_log['umidade_ambiente_pct']} %\n"
                )

            data_text.configure(state="disabled")

        def set_status(texto, cor="#55ff88"):
            status_var.set(texto)
            status_label.configure(fg=cor)

        def atualizar_progresso_ui(restante_s, stroke_atual, total_strokes):
            minutos = int(restante_s) // 60
            segundos = int(restante_s) % 60
            texto = f"Restante: {minutos:02d}:{segundos:02d}  |  Strokes: {stroke_atual}/{total_strokes}"
            root.after(0, lambda: progresso_var.set(texto))

        def parar_emergencia(event=None):
            if emergencia.is_set():
                return

            print("🛑 PARADA DE EMERGÊNCIA acionada!")
            emergencia.set()
            maquina.parada_emergencia()
            set_status("PARADA DE EMERGÊNCIA - TOQUE EM RESET (R)", "#ff4444")

        def liberar_emergencia(event=None):
            if not emergencia.is_set():
                return

            emergencia.clear()
            set_status("AGUARDANDO QR CODE", "#55ff88")
            codigo_var.set("Nenhuma sela reconhecida")
            progresso_var.set("Tempo restante: --:--  |  Strokes: 0/0")
            print("🟢 Emergência liberada. Máquina pronta para nova leitura.")

        # Rodapé com botões Touchscreen + Atalhos C e R
        footer = tk.Frame(root, bg="#101820")
        footer.pack(fill="x", padx=16, pady=(6, 10))

        btn_emergencia = tk.Button(
            footer,
            text="🛑 PARADA DE EMERGÊNCIA (C)",
            font=("DejaVu Sans", 12, "bold"),
            bg="#dc2626",
            fg="white",
            activebackground="#991b1b",
            activeforeground="white",
            relief="flat",
            padx=14,
            pady=6,
            command=parar_emergencia
        )
        btn_emergencia.pack(side="left")

        btn_reset = tk.Button(
            footer,
            text="🔄 RESETAR MÁQUINA (R)",
            font=("DejaVu Sans", 12, "bold"),
            bg="#2563eb",
            fg="white",
            activebackground="#1d4ed8",
            activeforeground="white",
            relief="flat",
            padx=14,
            pady=6,
            command=liberar_emergencia
        )
        btn_reset.pack(side="right")

        def perguntar_confirmacao(item):
            """
            Mostra um popup modal com os botões SIM/NÃO perguntando se pode
            iniciar a mistura.
            """
            resposta_evento = threading.Event()
            resposta = {"valor": False}

            def criar_popup():
                popup = tk.Toplevel(root)
                popup.title("Confirmação")
                popup.configure(bg="#101820")
                popup.resizable(False, False)
                popup.attributes("-topmost", True)
                popup.grab_set()

                largura, altura = 480, 240
                pos_x = root.winfo_x() + (800 - largura) // 2
                pos_y = root.winfo_y() + (480 - altura) // 2
                popup.geometry(f"{largura}x{altura}+{pos_x}+{pos_y}")

                tk.Label(
                    popup,
                    text=f"Começar a mistura?\n\nSela: {item.get('code', 'N/A')} ({item.get('name', '')})",
                    font=("DejaVu Sans", 16, "bold"),
                    fg="white",
                    bg="#101820",
                    justify="center"
                ).pack(pady=(24, 18))

                btn_frame = tk.Frame(popup, bg="#101820")
                btn_frame.pack(pady=6)

                def escolher(valor):
                    if resposta_evento.is_set():
                        return
                    resposta["valor"] = valor
                    resposta_evento.set()
                    if popup.winfo_exists():
                        popup.grab_release()
                        popup.destroy()

                tk.Button(
                    btn_frame, text="✅  SIM", font=("DejaVu Sans", 16, "bold"),
                    bg="#2ecc71", fg="white", activebackground="#27ae60",
                    width=10, height=2, relief="flat",
                    command=lambda: escolher(True)
                ).pack(side="left", padx=20)

                tk.Button(
                    btn_frame, text="❌  NÃO", font=("DejaVu Sans", 16, "bold"),
                    bg="#e74c3c", fg="white", activebackground="#c0392b",
                    width=10, height=2, relief="flat",
                    command=lambda: escolher(False)
                ).pack(side="left", padx=20)

                def verificar_emergencia_ou_fechamento():
                    if emergencia.is_set() or encerrando.is_set():
                        escolher(False)
                        return
                    if popup.winfo_exists():
                        popup.after(150, verificar_emergencia_ou_fechamento)

                popup.after(150, verificar_emergencia_ou_fechamento)
                popup.protocol("WM_DELETE_WINDOW", lambda: escolher(False))

            root.after(0, criar_popup)
            return resposta_evento, resposta

        def fechar():
            encerrando.set()
            emergencia.set()
            maquina.parada_emergencia()

            try:
                root.destroy()
            except tk.TclError:
                pass

        # C = emergência. R = reset/liberação.
        root.bind_all("<KeyPress-c>", parar_emergencia)
        root.bind_all("<KeyPress-C>", parar_emergencia)
        root.bind_all("<KeyPress-r>", liberar_emergencia)
        root.bind_all("<KeyPress-R>", liberar_emergencia)
        root.protocol("WM_DELETE_WINDOW", fechar)

        def executar():
            while not encerrando.is_set():
                if emergencia.is_set():
                    time.sleep(0.1)
                    continue

                root.after(
                    0,
                    lambda: (
                        set_status("AGUARDANDO QR CODE", "#55ff88"),
                        codigo_var.set("Aponte a câmera para o QR Code"),
                        progresso_var.set("Tempo restante: --:--  |  Strokes: 0/0")
                    )
                )

                try:
                    item = recognizer.esperar_leitura(emergencia)
                except Exception as e:
                    print(f"❌ Erro na câmera: {e}")
                    root.after(
                        0,
                        lambda e=e: set_status("ERRO NA CÂMERA", "#ff4444")
                    )
                    time.sleep(1)
                    continue

                if encerrando.is_set():
                    break

                if emergencia.is_set() or item is None:
                    continue

                root.after(0, mostrar_dados, item)
                root.after(
                    0,
                    lambda item=item: (
                        codigo_var.set(f"SELA: {item.get('code', 'N/A')}"),
                        set_status("QR RECONHECIDO", "#55ddff")
                    )
                )

                # --- Confirmação do usuário antes de iniciar a mistura ---
                root.after(0, lambda: set_status("AGUARDANDO CONFIRMAÇÃO", "#ffdd55"))
                resposta_evento, resposta = perguntar_confirmacao(item)

                while not resposta_evento.is_set():
                    if encerrando.is_set():
                        break
                    time.sleep(0.1)

                if encerrando.is_set():
                    break

                if emergencia.is_set():
                    continue

                if not resposta["valor"]:
                    print("🚫 Mistura cancelada pelo usuário.")
                    root.after(0, lambda: (
                        codigo_var.set("Nenhuma sela reconhecida"),
                        set_status("MISTURA CANCELADA", "#ff8844")
                    ))
                    time.sleep(1.2)
                    continue

                rpm = item.get("rpm", 100)
                tempo_min = item.get("tempo_min", 3)
                ciclos = item.get("ciclo_strokes", 90)
                tempo_total_s = float(tempo_min) * 60.0

                root.after(
                    0,
                    lambda: set_status("CICLO EM EXECUÇÃO", "#ffaa33")
                )

                sucesso = maquina.executar_ciclo(
                    rpm=rpm,
                    tempo_total_s=tempo_total_s,
                    total_ciclos_pistao=ciclos,
                    stop_event=emergencia,
                    progress_callback=atualizar_progresso_ui
                )

                if emergencia.is_set():
                    root.after(
                        0,
                        lambda: set_status(
                            "PARADA DE EMERGÊNCIA - TOQUE EM RESET (R)",
                            "#ff4444"
                        )
                    )
                    continue

                if sucesso:
                    registro_log = rastreio.registrar_log(item)
                    rastreio.imprimir_etiqueta_zpl(registro_log)
                    root.after(0, mostrar_dados, item, registro_log)
                    root.after(
                        0,
                        lambda: set_status(
                            "CICLO CONCLUÍDO - ETIQUETA IMPRESSA",
                            "#55ff88"
                        )
                    )
                    time.sleep(2.5)

        thread = threading.Thread(target=executar, daemon=True)
        thread.start()

        root.mainloop()

    except KeyboardInterrupt:
        print("\n[Aviso] Interrupção acionada pelo usuário (Ctrl+C).")
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        import traceback
        traceback.print_exc()
        if root is not None:
            try:
                messagebox.showerror("Erro", str(e))
            except Exception:
                pass
    finally:
        if maquina:
            maquina.finalizar()


if __name__ == "__main__":
    main()
