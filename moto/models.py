from django.db import models
from django.contrib.auth.models import User
from datetime import date

class DiarioMoto(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    data = models.DateField(default=date.today)
    km_rodado = models.IntegerField(blank=True, null=True) # Opcional: saber quanto rodou
    
    # Ganhos do dia (Soma total, mas podemos detalhar se quiser)
    ganho_uber = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    ganho_ifood = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    ganho_99 = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    ganho_particular = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    
    # Gastos do dia
    gasto_combustivel = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    gasto_manutencao = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    gasto_alimentacao = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    class Meta:
        unique_together = ('usuario', 'data') # Evita criar dois registros para o mesmo dia

    def lucro_liquido(self):
        total_ganhos = self.ganho_uber + self.ganho_ifood + self.ganho_99 + self.ganho_particular
        total_gastos = self.gasto_combustivel + self.gasto_manutencao + self.gasto_alimentacao
        return total_ganhos - total_gastos

    def __str__(self):
        return f"Diário {self.data} - {self.usuario.username}"

class PendenciaReceber(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    descricao = models.CharField(max_length=100) # Ex: Corrida do João
    valor = models.DecimalField(max_digits=8, decimal_places=2)
    data_origem = models.DateField(default=date.today)
    recebido = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.descricao} - {self.valor}"