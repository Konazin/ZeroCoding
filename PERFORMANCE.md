# Desempenho

ZeroCoding mantém a instalação e o runtime padrão em Python. A latência de inferência pertence principalmente ao modelo e ao hardware; os números da aplicação devem separar tempo de montagem do pedido, primeiro token e geração.

O agente mede localmente montagem, estimativa de tokens de entrada, primeiro token, duração total e quantidade de tools. Quando o provider informa uso ou duração de prefill/geração, esses dados ficam em memória para `/status`; nenhum prompt ou conteúdo de arquivo é gravado como telemetria.

Para comparar modos, use o mesmo modelo, hardware, histórico e contexto, registrando separadamente a primeira execução com modelo frio e as execuções com modelo carregado. `fast` limita entrada a 1.024 tokens estimados e 3 etapas de tools; `code` usa 2.048 e 6; `reason` e `smart` usam 3.072 e 8. O prompt permanente tem no máximo 64 tokens. A estimativa padrão é quatro caracteres por token e deve ser tratada como aproximação.

Rust só será considerado depois de perfilamento local. Um protótipo precisa mostrar que uma operação de CPU consome pelo menos 20% do tempo local medido, acelerar essa operação em pelo menos 2× e melhorar o fluxo completo em pelo menos 10%. A extensão deve ser opcional, exposta por função Python estável e manter fallback Python. Rede, permissões e acesso a arquivos permanecem no runtime Python.
