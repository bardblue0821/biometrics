# -*- coding: utf-8 -*-

#
# RNN Attention Encoder-Decoderモデルを学習します．
#

# Pytorchを用いた処理に必要なモジュールをインポート
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torch import optim

# 作成したDatasetクラスをインポート
from my_dataset import SequenceDataset

# 数値演算用モジュール(numpy)をインポート
import numpy as np

# プロット用モジュール(matplotlib)をインポート
import matplotlib.pyplot as plt

# 認識エラー率を計算するモジュールをインポート
import levenshtein

# モデルの定義をインポート
from my_model import MyE2EModel

# json形式の入出力を行うモジュールをインポート
import json

# os, sys, shutilモジュールをインポート
import os
import sys
import shutil


#
# メイン関数
#
if __name__ == "__main__":
    
    #
    # 設定ここから
    #

    # トークンの単位
    # phone:音素  kana:かな  char:キャラクター
    unit = 'phone'

    # 学習データの特徴量(feats.scp)が存在するディレクトリ
    feat_dir_train = '../01compute_features/fbank/train_small'
    # 開発データの特徴量(Feats.scp)が存在するディレクトリ
    feat_dir_dev = '../01compute_features/fbank/dev'

    # 実験ディレクトリ
    # train_set_name = 'train_small' or 'train_large'
    train_set_name = os.path.basename(feat_dir_train) 
    exp_dir = './exp_' + os.path.basename(feat_dir_train) 

    # 学習/開発データの特徴量リストファイル
    feat_scp_train = os.path.join(feat_dir_train, 'feats.scp')
    feat_scp_dev = os.path.join(feat_dir_dev, 'feats.scp')

    # 学習/開発データのラベルファイル
    label_train = os.path.join(exp_dir, 'data', unit,
                               'label_'+train_set_name)
    label_dev = os.path.join(exp_dir, 'data', unit,
                             'label_dev')
    
    # 訓練データから計算された特徴量の平均/標準偏差ファイル
    mean_std_file = os.path.join(feat_dir_train, 'mean_std.txt')

    # トークンリスト
    token_list_path = os.path.join(exp_dir, 'data', unit,
                                   'token_list')
    # 学習結果を出力するディレクトリ
    output_dir = os.path.join(exp_dir, unit+'_model_attention')

    # ミニバッチに含める発話数
    batch_size = 10

    # 最大エポック数
    max_num_epoch = 60

    # Encoderの設定
    # 中間層のレイヤー数
    enc_num_layers = 5
    # 層ごとのsub sampling設定
    # [1, 2, 2, 1, 1]の場合は，2層目と3層目において，
    # フレームを1/2に間引く(結果的にフレーム数が1/4になる)
    enc_sub_sample = [1, 2, 2, 1, 1]
    # RNNのタイプ(LSTM or GRU)
    enc_rnn_type = 'GRU'
    # 中間層の次元数
    enc_hidden_dim = 320
    # Projection層の次元数
    enc_projection_dim = 320
    # bidirectional を用いるか(Trueなら用いる)
    enc_bidirectional = True

    # Attention, Decoderの設定
    # RNN層のレイヤー数
    dec_num_layers = 1
    # RNN層の次元数
    dec_hidden_dim = 300
    # Attentionの次元数
    att_hidden_dim = 320
    # LocationAwareAttentionにおけるフィルタサイズ
    att_filter_size = 100
    # LocationAwareAttentionにおけるフィルタ数
    att_filter_num = 10
    # LocationAwareAttentionにおけるtemperature
    att_temperature = 2.0

    # 初期学習率
    initial_learning_rate = 1.0

    # Clipping Gradientの閾値
    clip_grad_threshold = 5.0

    # 学習率の減衰やEarly stoppingの
    # 判定を開始するエポック数
    # (= 最低限このエポックまではどれだけ
    # validation結果が悪くても学習を続ける)
    lr_decay_start_epoch = 7

    # 学習率を減衰する割合
    # (減衰後学習率 <- 現在の学習率*lr_decay_factor)
    # 1.0以上なら，減衰させない
    lr_decay_factor = 0.5

    # Early stoppingの閾値
    # 最低損失値を更新しない場合が
    # 何エポック続けば学習を打ち切るか
    early_stop_threshold = 3

    # 学習過程で，認識エラー率を計算するか否か
    # 認識エラー率の計算は時間がかかるので注意
    # (ここではvalidationフェーズのみTrue(計算する)にしている)
    evaluate_error = {'train': False, 'validation': True}

    #
    # 設定ここまで
    #
    
    # Attention重み行列情報の保存先
    out_att_dir = os.path.join(output_dir, 'att_matrix')
    
    # 出力ディレクトリが存在しない場合は作成する
    os.makedirs(out_att_dir, exist_ok=True)

    # 設定を辞書形式にする
    config = {'enc_rnn_type': enc_rnn_type,
              'enc_num_layers': enc_num_layers,
              'enc_sub_sample': enc_sub_sample, 
              'enc_hidden_dim': enc_hidden_dim,
              'enc_projection_dim': enc_projection_dim,
              'enc_bidirectional': enc_bidirectional,
              'dec_num_layers': dec_num_layers,
              'dec_hidden_dim': dec_hidden_dim,
              'att_hidden_dim': att_hidden_dim,
              'att_filter_size': att_filter_size,
              'att_filter_num': att_filter_num,
              'att_temperature': att_temperature,
              'batch_size': batch_size,
              'max_num_epoch': max_num_epoch,
              'clip_grad_threshold': clip_grad_threshold,
              'initial_learning_rate': initial_learning_rate,
              'lr_decay_start_epoch': lr_decay_start_epoch, 
              'lr_decay_factor': lr_decay_factor,
              'early_stop_threshold': early_stop_threshold
             }

    # 設定をJSON形式で保存する
    conf_file = os.path.join(output_dir, 'config.json')
    with open(conf_file, mode='w') as f:
        json.dump(config, f, indent=4)

    # 特徴量の平均/標準偏差ファイルを読み込む
    with open(mean_std_file, mode='r') as f:
        # 全行読み込み
        lines = f.readlines()
        # 1行目(0始まり)が平均値ベクトル(mean)，
        # 3行目が標準偏差ベクトル(std)
        mean_line = lines[1]
        std_line = lines[3]
        # スペース区切りのリストに変換
        feat_mean = mean_line.split()
        feat_std = std_line.split()
        # numpy arrayに変換
        feat_mean = np.array(feat_mean, 
                                dtype=np.float32)
        feat_std = np.array(feat_std, 
                               dtype=np.float32)
    # 平均/標準偏差ファイルをコピーする
    shutil.copyfile(mean_std_file,
                    os.path.join(output_dir, 'mean_std.txt'))

    # 次元数の情報を得る
    feat_dim = np.size(feat_mean)

    # トークンリストをdictionary型で読み込む
    # このとき，0番目は blank と定義する
    # (ただし，このプログラムではblankは使われない)
    token_list = {0: '<blank>'}
    with open(token_list_path, mode='r') as f:
        # 1行ずつ読み込む
        for line in f: 
            # 読み込んだ行をスペースで区切り，
            # リスト型の変数にする
            parts = line.split()
            # 0番目の要素がトークン，1番目の要素がID
            token_list[int(parts[1])] = parts[0]

    # <eos>トークンをユニットリストの末尾に追加
    eos_id = len(token_list)
    token_list[eos_id] = '<eos>'
    # 本プログラムでは、<sos>と<eos>を
    # 同じトークンとして扱う
    sos_id = eos_id

    # トークン数(blankを含む)
    num_tokens = len(token_list)
    
    # ニューラルネットワークモデルを作成する
    # 入力の次元数は特徴量の次元数，
    # 出力の次元数はトークン数となる
    model = MyE2EModel(dim_in=feat_dim,
                       dim_enc_hid=enc_hidden_dim,
                       dim_enc_proj=enc_projection_dim, 
                       dim_dec_hid=dec_hidden_dim,
                       dim_out=num_tokens,
                       dim_att=att_hidden_dim, 
                       att_filter_size=att_filter_size,
                       att_filter_num=att_filter_num,
                       sos_id=sos_id, 
                       att_temperature=att_temperature,
                       enc_num_layers=enc_num_layers,
                       dec_num_layers=dec_num_layers,
                       enc_bidirectional=enc_bidirectional,
                       enc_sub_sample=enc_sub_sample, 
                       enc_rnn_type=enc_rnn_type)
    print(model)

    # オプティマイザを定義
    optimizer = optim.Adadelta(model.parameters(),
                               lr=initial_learning_rate,
                               rho=0.95,
                               eps=1e-8,
                               weight_decay=0.0)

    # 訓練/開発データのデータセットを作成する
    train_dataset = SequenceDataset(feat_scp_train,
                                    label_train,
                                    feat_mean,
                                    feat_std)

    # 開発データのデータセットを作成する
    dev_dataset = SequenceDataset(feat_scp_dev,
                                  label_dev,
                                  feat_mean,
                                  feat_std)

    # 訓練データのDataLoaderを呼び出す
    # 訓練データはシャッフルして用いる
    #  (num_workerは大きい程処理が速くなりますが，
    #   PCに負担が出ます．PCのスペックに応じて
    #   設定してください)
    train_loader = DataLoader(train_dataset,
                              batch_size=batch_size,
                              shuffle=True,
                              num_workers=4)
    # 開発データのDataLoaderを呼び出す
    # 開発データはデータはシャッフルしない
    dev_loader = DataLoader(dev_dataset,
                            batch_size=batch_size,
                            shuffle=False,
                            num_workers=4)

    # クロスエントロピー損失を用いる．ゼロ埋めしているラベルを
    # 損失計算に考慮しないようにするため，ignore_index=0を設定
    criterion = nn.CrossEntropyLoss(ignore_index=0)

    # CUDAが使える場合はモデルパラメータをGPUに，
    # そうでなければCPUに配置する
    if torch.cuda.is_available():
        device = torch.device('cuda')
    else:
        device = torch.device('cpu')
    model = model.to(device)

    # モデルをトレーニングモードに設定する
    model.train()

    # 訓練データの処理と開発データの処理を
    # for でシンプルに記述するために，辞書データ化しておく
    dataset_loader = {'train': train_loader,
                      'validation': dev_loader}

    # 各エポックにおける損失値と誤り率の履歴
    loss_history = {'train': [],
                    'validation': []}
    error_history = {'train': [],
                     'validation': []}

    # 本プログラムでは，validation時の損失値が
    # 最も低かったモデルを保存する．
    # そのため，最も低い損失値，
    # そのときのモデルとエポック数を記憶しておく
    best_loss = -1
    best_model = None
    best_epoch = 0
    # Early stoppingフラグ．Trueになると学習を打ち切る
    early_stop_flag = False
    # Early stopping判定用(損失値の最低値が
    # 更新されないエポックが何回続いているか)のカウンタ
    counter_for_early_stop = 0

    # ログファイルの準備
    log_file = open(os.path.join(output_dir,
                                 'log.txt'),
                                 mode='w')
    log_file.write('epoch\ttrain loss\t'\
                   'train err\tvalid loss\tvalid err')

    # エポックの数だけループ
    for epoch in range(max_num_epoch):
        # early stopフラグが立っている場合は，
        # 学習を打ち切る
        if early_stop_flag:
            print('    Early stopping.'\
                  ' (early_stop_threshold = %d)' \
                  % (early_stop_threshold))
            log_file.write('\n    Early stopping.'\
                           ' (early_stop_threshold = %d)' \
                           % (early_stop_threshold))
            break

        # エポック数を表示
        print('epoch %d/%d:' % (epoch+1, max_num_epoch))
        log_file.write('\n%d\t' % (epoch+1))

        # trainフェーズとvalidationフェーズを交互に実施する
        for phase in ['train', 'validation']:
            # このエポックにおける累積損失値と発話数
            total_loss = 0
            total_utt = 0
            # このエポックにおける累積認識誤り文字数と総文字数
            total_error = 0
            total_token_length = 0

            # 各フェーズのDataLoaderから1ミニバッチ
            # ずつ取り出して処理する．
            # これを全ミニバッチ処理が終わるまで繰り返す．
            # ミニバッチに含まれるデータは，
            # 音声特徴量，ラベル，フレーム数，
            # ラベル長，発話ID
            for (features, labels, feat_lens,
                 label_lens, utt_ids) \
                    in dataset_loader[phase]:

                # PackedSequence の仕様上，
                # ミニバッチがフレーム長の降順で
                # ソートされている必要があるため，
                # ソートを実行する
                sorted_lens, indices = \
                    torch.sort(feat_lens.view(-1),
                               dim=0,
                               descending=True)
                features = features[indices]
                labels = labels[indices]
                feat_lens = sorted_lens
                label_lens = label_lens[indices]

                #
                # ラベルの末尾に<eos>を付与する
                #
                # ゼロ埋めにより全体の長さを1増やす
                labels = torch.cat((labels,
                                    torch.zeros(labels.size()[0],
                                    1,
                                    dtype=torch.long)), dim=1)
                # 末尾に<eos>追加
                for m, length in enumerate(label_lens):
                    labels[m][length] = eos_id
                label_lens += 1

                # 現時点でラベルのテンソルサイズは
                # [発話数 x 全データの最大ラベル長]
                # これを[発話数 x バッチ内の最大ラベル長]
                # に切る。(decoder部の冗長な処理を少なくするため。)
                labels = labels[:,:torch.max(label_lens)]

                # CUDAが使える場合はデータをGPUに，
                # そうでなければCPUに配置する
                features, labels = \
                    features.to(device), labels.to(device)

                # 勾配をリセット
                optimizer.zero_grad()

                # モデルの出力を計算(フォワード処理)
                outputs, _ = model(features, feat_lens, labels)

                # クロスエントロピー損失関数の入力は
                # [(バッチサイズ*フレーム数) x クラス数]
                # なので，viewで変形する
                b_size, t_size, _ = outputs.size()
                loss = criterion(outputs.view(b_size*t_size, 
                                 num_tokens), labels.view(-1))
                # ラベルの平均長を掛ける
                loss *= np.mean(label_lens.numpy())

                # 訓練フェーズの場合は，誤差逆伝搬を実行し，
                # モデルパラメータを更新する
                if phase == 'train':
                    # 勾配を計算する
                    loss.backward()
                    # Cliping Gradient により勾配が
                    # 閾値以下になるよう調整する
                    torch.nn.utils.clip_grad_norm_(\
                                              model.parameters(),
                                              clip_grad_threshold)
                    # オプティマイザにより，パラメータを更新する
                    optimizer.step()

                # 認識エラーの算出をTrueにしている場合は，算出する
                if evaluate_error[phase]:
                    # バッチ内の1発話ごとに誤りを計算
                    for n in range(outputs.size(0)):
                        # 各ステップのデコーダ出力を得る
                        _, hyp_per_step = torch.max(outputs[n], 1)
                        # numpy.array型に変換
                        hyp_per_step = hyp_per_step.cpu().numpy()
                        # 認識結果の文字列を取得
                        hypothesis = []
                        for m in hyp_per_step[:label_lens[n]]:
                            hypothesis.append(token_list[m])
                        # 正解の文字列を取得
                        reference = []
                        for m in labels[n][:label_lens[n]].cpu().numpy():
                            reference.append(token_list[m])
                        # 認識誤りを計算
                        (error, substitute, 
                         delete, insert, ref_length) = \
                            levenshtein.calculate_error(hypothesis,
                                                        reference)
                        # 誤り文字数を累積する
                        total_error += error
                        # 文字の総数を累積する
                        total_token_length += ref_length

                # 開発データについて、
                # Attention重み行列を1サンプル画像にして保存
                if phase == 'validation' and total_loss == 0:
                    # バッチの内ゼロ番目のサンプルを使う
                    idx = torch.nonzero(indices==0, 
                                        as_tuple=False).view(-1)[0]

                    out_name = os.path.join(out_att_dir,
                                  '%s_ep%d.png' % (utt_ids[0],
                                  epoch+1))
                    # Attention重み行列保存の関数を実行
                    model.save_att_matrix(idx, out_name)

                # 損失値を累積する
                total_loss += loss.item()
                # 処理した発話数をカウントする
                total_utt += outputs.size(0)

            #
            # このフェーズにおいて，1エポック終了
            # 損失値，認識エラー率，モデルの保存等を行う
            # 

            # 損失値の累積値を，処理した発話数で割る
            epoch_loss = total_loss / total_utt
            # 画面とログファイルに出力する
            print('    %s loss: %f' \
                  % (phase, epoch_loss))
            log_file.write('%.6f\t' % (epoch_loss))
            # 履歴に加える
            loss_history[phase].append(epoch_loss)

            # 認識エラー率を計算する
            if evaluate_error[phase]:
                # 総誤りトークン数を，
                # 総トークン数で割ってエラー率に換算
                epoch_error = 100.0 * total_error \
                            / total_token_length
                # 画面とログファイルに出力する
                print('    %s token error rate: %f %%' \
                    % (phase, epoch_error))
                log_file.write('%.6f\t' % (epoch_error))
                # 履歴に加える
                error_history[phase].append(epoch_error)
            else:
                # エラー率を計算していない場合
                log_file.write('     ---     \t')

            #
            # validationフェーズ特有の処理
            #
            if phase == 'validation':
                if epoch == 0 or best_loss > epoch_loss:
                    # 損失値が最低値を更新した場合は，
                    # その時のモデルを保存する
                    best_loss = epoch_loss
                    torch.save(model.state_dict(), 
                               output_dir+'/best_model.pt')
                    best_epoch = epoch
                    # Early stopping判定用の
                    # カウンタをリセットする
                    counter_for_early_stop = 0
                else:
                    # 最低値を更新しておらず，
                    if epoch+1 >= lr_decay_start_epoch:
                        # かつlr_decay_start_epoch以上の
                        # エポックに達している場合
                        if counter_for_early_stop+1 \
                               >= early_stop_threshold:
                            # 更新していないエポックが，
                            # 閾値回数以上続いている場合，
                            # Early stopping フラグを立てる
                            early_stop_flag = True
                        else:
                            # Early stopping条件に
                            # 達していない場合は
                            # 学習率を減衰させて学習続行
                            if lr_decay_factor < 1.0:
                                for i, param_group \
                                      in enumerate(\
                                      optimizer.param_groups):
                                    if i == 0:
                                        lr = param_group['lr']
                                        dlr = lr_decay_factor \
                                            * lr
                                        print('    (Decay '\
                                          'learning rate:'\
                                          ' %f -> %f)' \
                                          % (lr, dlr))
                                        log_file.write(\
                                          '(Decay learning'\
                                          ' rate: %f -> %f)'\
                                           % (lr, dlr))
                                    param_group['lr'] = dlr
                            # Early stopping判定用の
                            # カウンタを増やす
                            counter_for_early_stop += 1

    #
    # 全エポック終了
    # 学習済みモデルの保存とログの書き込みを行う
    #
    print('---------------Summary'\
          '------------------')
    log_file.write('\n---------------Summary'\
                   '------------------\n')

    # 最終エポックのモデルを保存する
    torch.save(model.state_dict(), 
               os.path.join(output_dir,'final_model.pt'))
    print('Final epoch model -> %s/final_model.pt' \
          % (output_dir))
    log_file.write('Final epoch model ->'\
                   ' %s/final_model.pt\n' \
                   % (output_dir))

    # 最終エポックの情報
    for phase in ['train', 'validation']:
        # 最終エポックの損失値を出力
        print('    %s loss: %f' \
              % (phase, loss_history[phase][-1]))
        log_file.write('    %s loss: %f\n' \
                       % (phase, loss_history[phase][-1]))
        # 最終エポックのエラー率を出力    
        if evaluate_error[phase]:
            print('    %s token error rate: %f %%' \
                % (phase, error_history[phase][-1]))
            log_file.write('    %s token error rate: %f %%\n' \
                % (phase, error_history[phase][-1]))
        else:
            print('    %s token error rate: (not evaluated)' \
                % (phase))
            log_file.write('    %s token error rate: '\
                '(not evaluated)\n' % (phase))

    # ベストエポックの情報
    # (validationの損失が最小だったエポック)
    print('Best epoch model (%d-th epoch)'\
          ' -> %s/best_model.pt' \
          % (best_epoch+1, output_dir))
    log_file.write('Best epoch model (%d-th epoch)'\
          ' -> %s/best_model.pt\n' \
          % (best_epoch+1, output_dir))
    for phase in ['train', 'validation']:
        # ベストエポックの損失値を出力
        print('    %s loss: %f' \
              % (phase, loss_history[phase][best_epoch]))
        log_file.write('    %s loss: %f\n' \
              % (phase, loss_history[phase][best_epoch]))
        # ベストエポックのエラー率を出力
        if evaluate_error[phase]:
            print('    %s token error rate: %f %%' \
                  % (phase, error_history[phase][best_epoch]))
            log_file.write('    %s token error rate: %f %%\n' \
                  % (phase, error_history[phase][best_epoch]))
        else:
            print('    %s token error rate: '\
                  '(not evaluated)' % (phase))
            log_file.write('    %s token error rate: '\
                  '(not evaluated)\n' % (phase))

    # 損失値の履歴(Learning Curve)グラフにして保存する
    fig1 = plt.figure()
    for phase in ['train', 'validation']:
        plt.plot(loss_history[phase],
                 label=phase+' loss')
    plt.xlabel('Epoch')
    plt.ylabel('Loss')
    fig1.legend()
    fig1.savefig(output_dir+'/loss.png')

    # 認識誤り率の履歴グラフにして保存する
    fig2 = plt.figure()
    for phase in ['train', 'validation']:
        if evaluate_error[phase]:
            plt.plot(error_history[phase],
                     label=phase+' error')
    plt.xlabel('Epoch')
    plt.ylabel('Error [%]')
    fig2.legend()
    fig2.savefig(output_dir+'/error.png')

    # ログファイルを閉じる
    log_file.close()


