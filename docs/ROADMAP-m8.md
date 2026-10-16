# M8 — Integridade e privacidade das sessões locais

**Estado:** implementação local e validação automatizada concluídas; confirmação da instalação empacotada pela CI pendente. Iniciada por autorização explícita em 2026-10-16. A suíte automatizada usa providers sintéticos; depois, o usuário autorizou o mega teste M7.2–M7.4 contra a IA local. Os resultados, incluindo gates reprovados, estão em [`MEGA-TEST-M7-M8-2026-10-16.md`](MEGA-TEST-M7-M8-2026-10-16.md).

## Objetivo

Permitir retomar sessões sem expor seu conteúdo a outros usuários da máquina, corromper o arquivo em uma interrupção, carregar a sessão errada ou deixar o usuário sem controle sobre o histórico persistido.

## Evidência no código

- `Session` persiste `history` e `context_files`; o histórico pode conter pedidos, respostas e resultados de ferramentas com trechos de código do workspace. `save_session_state` grava esses dados ao fim do turno.
- Antes do M8, `SessionManager.save` sobrescrevia o JSON diretamente e não restringia os modos POSIX.
- Antes do M8, `SessionManager.load` carregava a primeira correspondência de prefixo e sessões inválidas eram ignoradas sem aviso.
- A persistência ficava sempre ativa, e não havia remoção explícita de sessões pela TUI.
- Métricas têm um contrato separado e armazenam apenas números. O M8 deve preservar esse contrato e não passar a gravar prompts, respostas ou arquivos em `metrics`.

## Princípios

1. A sessão permanece local e em texto simples, protegida por permissões do sistema operacional. M8 não promete criptografia contra o próprio usuário, malware ou backups.
2. A compatibilidade com os arquivos atuais é obrigatória; leitura de uma sessão antiga nunca deve apagá-la nem reescrevê-la automaticamente.
3. Não apagar histórico automaticamente. O usuário controla a desativação, a remoção e qualquer limpeza por retenção.
4. Falha de gravação preserva a última cópia válida e retorna um erro claro, sem encerrar ou corromper o restante do agente.
5. CI e testes usam sessões e providers sintéticos. Este marco não requer modelo, servidor local nem chamadas de geração.

## Sequenciamento e autorização

O plano inicial colocava o M8 depois da revisão dos gates do M7:

- executar o mega teste local planejado para M7.2–M7.4 e registrar as métricas de qualidade, contagem e streaming;
- validar a instalação do pacote e seus recursos pela CI (M7.9);
- resolver os itens condicionais do M7 por evidência ou registrar que não foram acionados;
- obter revisão do usuário sobre os resultados e sobre o início do M8.

O usuário autorizou explicitamente o início do M8 antes desses gates. Depois, em 2026-10-16, autorizou executar o mega teste local M7.2–M7.4. Ele foi realizado; os gates de qualidade, contagem do fallback e latência/paridade do streaming não passaram. Isso não invalida a suíte sintética do M8.

## Marcos e estado da implementação

### M8.1 — Gravação privada e resistente a interrupções

**Estado:** implementação concluída e validada localmente.

- Criar o diretório de sessões com acesso somente ao usuário (`0700` em POSIX) e arquivos com modo restrito (`0600`); em plataformas sem esses modos, documentar e testar a proteção equivalente disponível.
- Aplicar as permissões também às sessões existentes quando forem arquivos regulares pertencentes ao usuário. Não seguir links simbólicos nem alterar arquivos de terceiros.
- Gravar por arquivo temporário no mesmo diretório, flush + `fsync`, `os.replace` e sincronização do diretório quando disponível. Remover temporários abandonados com segurança.
- Detectar diretório de sessões não gravável, link simbólico inesperado, JSON inválido e falha de substituição; preservar o original e reportar erro claro com o caminho quando aplicável. A listagem aponta IDs inválidos e orienta sua remoção explícita.

**Saída:** testes de permissão sob `umask 022`, gravação interrompida/substituição com erro, arquivo original intacto, criação de sessão e retomada em diretório isolado.

### M8.2 — Identidade e compatibilidade de sessões

**Estado:** implementação concluída e validada localmente.

- Usar IDs novos com entropia suficiente (UUID completo) e validar o formato antes de construir qualquer caminho.
- Fazer a busca exata primeiro. Para manter a UX atual, aceitar prefixo somente quando ele identifica exatamente uma sessão; prefixo ambíguo deve listar opções e nunca escolher a primeira.
- Adicionar versão de esquema e migração determinística em memória para os JSON atuais sem alterar o arquivo durante `load`.
- Distinguir JSON inválido, versão futura e ID inexistente. A listagem informa a quantidade e os IDs dos arquivos inválidos sem imprimir conteúdo; o usuário pode removê-los pelo ID completo.
- Validar os tipos dos campos usados na retomada; `/resume` sem ID, com ID inexistente ou com sessão malformada preserva a sessão e o histórico atuais.
- Derivar datas ausentes do `mtime` do arquivo legado, sem modificar o JSON, para uma migração estável em memória.

**Saída:** sessões atuais continuam retomáveis; testes cobrem IDs legados, IDs novos, colisão de prefixo, caracteres de caminho, JSON truncado e esquema futuro.

### M8.3 — Controles explícitos de persistência e remoção

**Estado:** implementação concluída e validada localmente.

- Preservar persistência habilitada por padrão para compatibilidade; adicionar opção de configuração e override de execução para não salvar sessões. Nesse modo, a sessão é efêmera e a TUI continua funcionando, mas `/resume` após sair não é prometido.
- Estender `/sessions` para listar apenas metadados úteis (ID, workspace, modelo, data, tamanho e quantidade de mensagens) e permitir remover uma sessão específica após confirmação explícita do ID completo.
- Adicionar limpeza total somente como ação explícita, confirmada e restrita ao diretório de sessões. Não apagar métricas, memória SQLite, configuração nem arquivos do workspace.
- Não introduzir expiração ou limite de sessões automático neste marco. Medir tamanho e frequência de uso antes de propor uma política padrão de retenção.

**Saída:** teste comprova que a opção efêmera não cria JSON; remoção afeta apenas a sessão escolhida; confirmação ausente ou divergente não remove nada; histórico antigo continua visível e retomável.

### M8.4 — Contrato de privacidade e validação

**Estado:** documentação e suíte local concluídas; confirmação da instalação pela CI pendente.

- Documentar quais dados entram em sessão, onde ficam, como desativar persistência e como excluir sessões. Deixar claro que o conteúdo é texto local sem criptografia.
- A cobertura automatizada inclui a separação entre métricas e conteúdo conversacional, e verifica que a listagem e os diagnósticos não imprimem prompts, respostas ou resultados de ferramentas.
- Cobertura automatizada preparada com TUI simulada para listagem, remoção, confirmação e modo efêmero; inclui erro de armazenamento na inicialização, retomada inválida e migração de timestamps legados.
- Auditoria final corrigiu validação de dados antes de gravar, retomada transacional quando a preparação do provider falha, preservação do estado em `/new` quando o armazenamento falha, a troca do workspace de ferramentas ao iniciar uma nova sessão e a gravação dupla da sessão durante a inicialização.
- Suíte completa após a estabilização: `239 passed, 10 subtests passed`; `compileall` e `git diff --check` passaram. A instalação não editável ainda precisa ser confirmada pela CI. Nenhum teste automatizado de M8 chama um modelo.

**Saída do M8:** compatibilidade com sessões existentes, armazenamento restrito e atômico, carregamento sem ambiguidade, controles de persistência/remoção documentados e suíte verde em plataforma suportada.

## Fora de escopo

- Criptografia própria ou gerenciamento de chaves; sincronização em nuvem; exportação de traces brutos.
- Exclusão automática, compressão ou sumarização por IA do histórico.
- Reversão de alterações no workspace, staging/commit/push do Git ou mudanças no fluxo de aprovação de arquivos.
- Mudança de provider/modelo, prompt de produção, orçamento ou recursos de extensão.

## Riscos e decisões recomendadas

- **Permissões não são criptografia:** recomendado documentar o risco residual e confiar na criptografia do disco fornecida pelo sistema, quando disponível.
- **Sessões antigas com permissões amplas:** aplicar modo restrito apenas a arquivos regulares do usuário; reportar os que não puderem ser corrigidos em segurança.
- **Compatibilidade de IDs curtos:** aceitar prefixo somente se único e rejeitar ambiguidade; nunca carregar por ordem lexicográfica.
- **Retenção:** manter sem exclusão automática inicialmente; apresentar tamanho/idade e oferecer remoção manual. Reavaliar com dados reais antes de definir limite padrão.

## Dependências

```text
M7: M7.2–M7.4 medidos (gates não passaram); validação de empacotamento pela CI pendente
  └── autorização explícita do usuário para iniciar M8
       └── M8.1 armazenamento seguro ── concluído
            └── M8.2 identidade e migração ── concluído
                 └── M8.3 controles de sessão ── concluído
                      └── M8.4 documentação e validação ── suíte local aprovada; CI de instalação pendente
```
