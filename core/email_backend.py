# core/email_backend.py

from django.core.mail.backends.base import BaseEmailBackend
from django.conf import settings
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

class BrevoBackend(BaseEmailBackend):
    """
    Este é o 'interceptador' de emails.
    Toda vez que o Django tentar enviar email, cai aqui.
    """
    
    def send_messages(self, email_messages):
        """
        O Django chama este método automaticamente.
        
        email_messages = lista de emails para enviar
        Exemplo: [EmailMessage(to=['user@email.com'], subject='Reset', body='...')]
        """
        
        # 1. Configura a API do Brevo com sua chave
        configuration = sib_api_v3_sdk.Configuration()
        configuration.api_key['api-key'] = settings.BREVO_API_KEY
        
        # 2. Cria cliente da API
        api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
            sib_api_v3_sdk.ApiClient(configuration)
        )
        
        num_sent = 0  # Contador de emails enviados
        
        # 3. Para cada email na lista
        for message in email_messages:
            try:
                # 4. Monta o email no formato da API do Brevo
                send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
                    to=[{"email": message.to[0]}],  # Para quem
                    sender={
                        "email": settings.DEFAULT_FROM_EMAIL,  # De quem
                        "name": "Minhas Finanças"
                    },
                    subject=message.subject,  # Assunto
                    html_content=message.body  # Corpo do email
                )
                
                # 5. Envia via API HTTP (não SMTP!)
                api_instance.send_transac_email(send_smtp_email)
                num_sent += 1
                
            except ApiException as e:
                # Se der erro e fail_silently=False, lança exceção
                if not self.fail_silently:
                    raise
        
        # 6. Retorna quantos emails foram enviados
        return num_sent