"""Fixtures dos testes ponta a ponta.

O PostgreSQL de teste (banco-modelo migrado e um banco por teste) é o mesmo da integração;
as fixtures são importadas daqui para não duplicar a subida do testcontainers.
"""

from tests.integration.conftest import banco, banco_modelo, servidor_postgres

__all__ = ["banco", "banco_modelo", "servidor_postgres"]
