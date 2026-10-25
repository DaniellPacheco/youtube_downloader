# Downloader e Cortador de YouTube

Uma aplicação web local para baixar vídeos autorizados do YouTube, criar cortes precisos e extrair áudio — sem enviar os seus arquivos para um servidor externo.

O projeto reúne `yt-dlp`, FFmpeg e FastAPI em uma interface simples: cole a URL, escolha o formato e acompanhe a tarefa até o arquivo final estar pronto.

> Use somente conteúdo que você tenha permissão para baixar e processar. O projeto não contorna DRM, login, conteúdo privado ou outras restrições de acesso.

## Para quem é

É especialmente útil para:

- Criadores que precisam separar trechos de entrevistas, podcasts, aulas ou lives gravadas.
- Editores que querem salvar um vídeo-fonte uma vez e produzir diversos cortes depois.
- Pessoas que precisam apenas do áudio de um vídeo, em M4A ou MP3.
- Quem prefere um fluxo local, com arquivos e biblioteca mantidos no próprio computador.

## O que ele faz

- Analisa uma URL de vídeo individual do YouTube e mostra título, duração, thumbnail e resoluções disponíveis.
- Baixa vídeos completos em MP4, combinando vídeo e áudio automaticamente quando o YouTube os fornece em streams separados.
- Cria cortes com início e fim exatos.
- Extrai áudio em M4A por padrão ou converte para MP3.
- Recorta um trecho do áudio em M4A ou MP3, com início e fim definidos.
- Mantém uma biblioteca de fontes e resultados para reutilizar o vídeo baixado em novos cortes.
- Processa uma tarefa por vez, exibindo status e progresso no navegador.
- Remove arquivos temporários e deixa fontes/resultados sob controle manual.

## Como funciona

```text
URL do YouTube
       │
       ▼
yt-dlp obtém metadados e baixa a fonte
       │
       ▼
FFmpeg junta streams, recorta ou extrai áudio
       │
       ▼
Biblioteca local → arquivo pronto para baixar
```

Quando possível, o FFmpeg apenas remuxa os streams para preservar qualidade e terminar rápido. Cortes precisos exigem recodificação; nesses casos, o projeto usa automaticamente a GPU NVIDIA via `h264_nvenc` quando disponível. Se não houver suporte ou o NVENC falhar, ele continua na CPU com `libx264`.

## Requisitos

- Windows, macOS ou Linux com Python 3.11+.
- [FFmpeg](https://ffmpeg.org/) e FFprobe disponíveis no `PATH`.
- Acesso à internet para analisar e baixar conteúdo autorizado.

Para aceleração por GPU, é necessário uma GPU NVIDIA com driver atualizado e uma compilação do FFmpeg que ofereça `h264_nvenc`.

### FFmpeg no Windows

Uma opção prática é instalar pelo WinGet:

```powershell
winget install --id Gyan.FFmpeg --exact
```

Feche e reabra o terminal após a instalação e confirme:

```powershell
ffmpeg -version
ffprobe -version
```

## Instalação

Clone o repositório e crie um ambiente virtual:

```powershell
git clone <URL-DO-REPOSITORIO>
cd youtube_downloader
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[test]"
```

No macOS/Linux, a ativação é:

```bash
source .venv/bin/activate
```

## Executando

```powershell
uvicorn app.main:app --reload
```

Abra [http://127.0.0.1:8000](http://127.0.0.1:8000) no navegador.

Na primeira tela:

1. Cole a URL e selecione **Analisar**.
2. Escolha entre vídeo completo, corte ou somente áudio.
3. Para cortes, informe início e fim em segundos, `MM:SS` ou `HH:MM:SS`.
4. Adicione à fila e acompanhe o progresso.
5. Baixe o resultado ou reutilize a fonte pela biblioteca.

Para recortar apenas o áudio, selecione **Somente áudio**, marque **Recortar áudio**,
informe início e fim e escolha M4A ou MP3. Sem marcar essa opção, o áudio completo é extraído.

## Converter um arquivo do computador para MP3

1. Clique em **Arquivo do computador**.
2. Selecione um áudio já salvo (por exemplo, um áudio do WhatsApp em OGG/Opus) ou um vídeo MP4.
3. Clique em **Usar arquivo**. O aplicativo verifica a faixa de áudio e seleciona MP3 como saída inicial.
4. Se quiser, ative o recorte ou os tratamentos por IA. Essas opções começam desmarcadas.
5. Clique em **Adicionar à fila** e depois em **Baixar arquivo**.

Formatos aceitos: OGG, Opus, MP4, M4A, MP3, WAV, AAC, FLAC, WebM, AMR, 3GP,
AIFF/AIF e WMA, desde que contenham uma faixa de áudio reconhecida pelo FFmpeg.
Também é possível escolher M4A como saída.

O usuário obtém o arquivo do WhatsApp por conta própria e seleciona o arquivo
no computador. O programa não se conecta ao WhatsApp. A importação guarda uma
cópia em `data/sources/`, que pode ser reutilizada pela biblioteca. Excluir essa
fonte da biblioteca apaga somente a cópia do aplicativo, preservando o original.
O limite padrão por arquivo é 512 MiB, configurável por `YTD_MAX_UPLOAD_BYTES`.

## IA local: remover música e reduzir ruído

Em **Somente áudio**, há duas opções independentes, **desmarcadas por padrão**:

- **Remover música de fundo:** separa os vocais do acompanhamento com o modelo `3_HP-Vocal-UVR`.
- **Reduzir ruídos de fundo:** aplica o modelo `UVR-DeNoise` e mantém a faixa sem ruído.

Você pode selecionar uma ou ambas. Quando ambas estão selecionadas, o aplicativo
remove a música primeiro e reduz o ruído depois. Se houver um corte, somente esse
trecho passa pela IA. O resultado é convertido para M4A ou MP3 ao final.
As fontes originais são preservadas.

### Instalação para NVIDIA (Windows, Python 3.11–3.13)

No PowerShell, dentro da pasta do projeto:

```powershell
.\.venv\Scripts\python.exe -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install -e ".[ai-gpu]"
```

Esse conjunto inclui suporte à geração RTX 50. Confira a GPU detectada:

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name() if torch.cuda.is_available() else 'CPU')"
```

Para CPU ou Apple Silicon, use `pip install -e ".[ai]"` no ambiente virtual.
Para AMD/Intel no Windows, há a alternativa experimental
`pip install -e ".[ai-directml]"`, em um ambiente compatível com `torch-directml`
(a disponibilidade de pacotes depende da versão do Python).
Escolha apenas um dos extras de IA para evitar instalar variantes conflitantes do ONNX Runtime.

Reinicie o aplicativo após instalar. A IA prefere CUDA/ROCm quando disponível,
depois Metal ou DirectML, e usa CPU quando não há GPU compatível configurada.
O suporte à GPU exige as bibliotecas e os drivers correspondentes; apenas ter uma
placa dedicada não garante que o ambiente Python consiga utilizá-la.
Se houver falha de execução na GPU, a etapa tenta novamente na CPU e avisa na fila.

No primeiro uso de cada tratamento, o aplicativo baixa o modelo e os metadados
para `data/models/` (ou `YTD_APP_DATA_DIR/models/`). Os arquivos ficam em cache
para as próximas execuções. O processamento é local e não envia seu áudio para
serviços externos. Depois que os modelos e metadados estiverem em cache, o
tratamento de uma fonte já armazenada pode funcionar sem internet.

A separação pode deixar resíduos e alterar a voz; vocais cantados ao fundo também
podem ser preservados. A qualidade depende da gravação. A primeira execução pode
demorar por causa do download e da preparação dos modelos. O progresso da IA
mostra etapas, sem estimar o tempo restante dentro de cada modelo.

Referências: [Audio Separator](https://github.com/nomadkaraoke/python-audio-separator)
e [instalação do PyTorch com CUDA](https://pytorch.org/get-started/previous-versions/).
Os modelos de separação são do projeto [Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui),
desenvolvidos por Anjok07 e colaboradores; o modelo de redução de ruído é de FoxJoy.

Os dados são gravados em `data/` por padrão. Para usar outro local, defina `YTD_APP_DATA_DIR` antes de iniciar o servidor:

```powershell
$env:YTD_APP_DATA_DIR = 'D:\Midias\youtube-downloader'
uvicorn app.main:app --reload
```

## Qualidade, desempenho e GPU

- Para vídeo completo, o aplicativo prioriza cópia direta de streams compatíveis; isso evita recodificação desnecessária.
- Para cortes precisos, o vídeo é recodificado para garantir os tempos solicitados.
- Com NVIDIA NVENC, cortes e conversões usam a GPU automaticamente e a interface mostra o progresso do FFmpeg.
- A codificação por GPU tende a ser muito mais rápida, mas pode gerar arquivos maiores que uma codificação equivalente por CPU. O equilíbrio entre velocidade, qualidade e tamanho pode variar conforme o vídeo.

## Testes

```powershell
pytest
```

Os testes cobrem validação de URLs e tempos, API, persistência, fila, progresso do FFmpeg, seleção de NVENC e fallback para CPU. Eles não acessam o YouTube nem baixam conteúdo real.

Os testes de IA reais são opcionais e usam um áudio sintético. Para executá-los
com os modelos locais (com download no primeiro uso):

```powershell
$env:YTD_RUN_AI_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_audio_ai_integration.py -q
Remove-Item Env:YTD_RUN_AI_TESTS
```

## Limites atuais

- Uso local e para uma pessoa por vez.
- Vídeos individuais do YouTube; playlists, canais e lives em andamento não fazem parte do MVP.
- Sem autenticação, cookies de login, downloads em lote ou publicação em redes sociais.
- IA para transcrição, sugestões de cortes, legendas e conversão vertical são evoluções futuras.

## Stack

- **Backend:** Python e FastAPI
- **Downloads:** yt-dlp
- **Mídia:** FFmpeg e FFprobe
- **Persistência:** SQLite
- **Interface:** HTML, CSS e JavaScript

## Licença e responsabilidade

Antes de usar, verifique os direitos autorais, as licenças e os termos aplicáveis ao conteúdo. Você é responsável pelo uso dos arquivos gerados por esta ferramenta.
