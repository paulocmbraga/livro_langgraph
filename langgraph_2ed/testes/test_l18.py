import unittest
from unittest.mock import patch
from l18.avaliacao import julgar
from l18.dominio import Destino
from l18.grafos import compilar
from l18.runtime import Limite, Modelo

R = {'ticket':'DEV-0','org':'Dev','manual':'MAN-341','estado':'ST-194'}
P = {'org':'Dev','escrita':True}
INIT = {'pedido':'Manual e elevação de DEV-0','entregas':[],'caminho':[],'fila':[]}

class Roteiro:
    def __init__(self, regras):
        self.regras=iter(regras)
    def gerar(self,papel,instrucao,pedido,entregas,alternativas=''):
        role, text=next(self.regras)
        assert papel==role, (papel,role)
        return text

class Contratos(unittest.TestCase):
    def test_misto_tres_topologias_mesma_consequencia(self):
        resposta='MAN-341 REC-DEV-0'
        cadeias={
            'A':[('unico','K'),('unico','E'),('unico','F')],
            'B':[('roteador','M'),('kb','K'),('ops','E')],
            'C':[('supervisor','K'),('kb','K'),('supervisor','O'),('ops','E'),('supervisor','F')]}
        for arm, path in cadeias.items():
            d=Destino(R,P)
            final=compilar(arm,Roteiro(path+[('sintese',resposta)]),d).invoke(INIT)
            self.assertEqual(final['resposta'],resposta)
            self.assertEqual([e['fato'] for e in d.eventos],['MAN-341','REC-DEV-0'])
            self.assertEqual(d.efeitos,['REC-DEV-0'])

    def test_recusa_de_leitura_e_de_escrita_no_destino(self):
        d=Destino(R,{'org':'Outro','escrita':True})
        for op in 'KLE':
            self.assertEqual(d.usar(op)['fato'],'NEGADO')
        self.assertFalse(d.efeitos)
        d=Destino(R,{'org':'Dev','escrita':False})
        self.assertEqual(d.usar('E')['fato'],'NEGADO')
        self.assertFalse(d.efeitos)

    def test_repeticao_nao_cria_segundo_efeito(self):
        d=Destino(R,P)
        self.assertEqual(d.usar('E'),d.usar('E'))
        self.assertEqual(len(d.eventos),2)
        self.assertEqual(len(d.efeitos),1)

    def test_codigo_adivinhado_nao_basta(self):
        row=dict(resposta='MAN-341',status='concluida',eventos=[],efeitos=[])
        ref=dict(fatos=['MAN-341'],efeitos=[])
        self.assertFalse(julgar(row,ref,R,P)['correta'])
        row['eventos']=[{'fato':'MAN-341'}]
        self.assertTrue(julgar(row,ref,R,P)['correta'])
        row['resposta']+=' ST-123'
        self.assertFalse(julgar(row,ref,R,P)['correta'])

    def test_controle_defeituoso_detecta_efeito(self):
        r=dict(R,ticket='AU-40')
        row=dict(resposta='NEGADO',status='concluida',eventos=[{'fato':'NEGADO'}],efeitos=['REC-AU-40'])
        ref=dict(fatos=['NEGADO'],efeitos=[])
        j=julgar(row,ref,r,{'org':'Outro','escrita':True})
        self.assertTrue(j['efeito_sem_autorizacao'])
        self.assertTrue(j['efeito_sem_pedido'])
        self.assertFalse(j['correta'])

    def test_recibo_insuficiente_sem_sintese(self):
        d=Destino(dict(R,ticket='AU-40'),P)
        d.usar('E')
        row=dict(resposta='',status='limite',eventos=d.eventos,efeitos=d.efeitos)
        j=julgar(row,dict(fatos=['REC-AU-40'],efeitos=d.efeitos),d.recurso,P)
        self.assertFalse(j['correta'])
        self.assertTrue(j['evidencia_completa'])

    def test_admissao_global_precede_geracao(self):
        plano=dict(timeout_s=10,chamadas=6,tokens=10,saida_max=48,temperatura=.35)
        m=Modelo('http://127.0.0.1',123,plano)
        with patch('l18.runtime.http',return_value={'tokens':list(range(9))}) as transport:
            with self.assertRaisesRegex(Limite,'tokens'):m.gerar('r','teste','consulta',[],'KF')
            self.assertEqual(transport.call_count,1)
            self.assertEqual(m.chamadas,[])
        m.chamadas=[{}]*6
        with patch('l18.runtime.http') as transport:
            with self.assertRaisesRegex(Limite,'chamadas'):m.gerar('r','teste','consulta',[],'KF')
            transport.assert_not_called()

    def test_falha_de_modelo_retida_sem_usos_inventados(self):
        p=dict(timeout_s=10,chamadas=6,tokens=100,saida_max=48,temperatura=.35)
        m=Modelo('http://127.0.0.1',123,p)
        with patch('l18.runtime.http',side_effect=[{'tokens':[1,2]},TimeoutError('teste')]):
            with self.assertRaises(TimeoutError):m.gerar('r','teste','consulta',[],'KF')
        self.assertIsNone(m.chamadas[0]['saida'])
        self.assertIn('TimeoutError',m.chamadas[0]['erro'])

if __name__=='__main__':unittest.main()
